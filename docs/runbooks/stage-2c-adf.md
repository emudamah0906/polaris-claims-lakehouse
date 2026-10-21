# Stage 2c: the ADF pipeline

Terraform made the factory, the `landing` container and the factory's access
(`infra/terraform/azure/data_factory.tf`). The pipeline is code too:

```
adf/linkedService/LS_ADLS_Polaris.json
adf/dataset/DS_Landing_Manifest.json, DS_Landing_Estimates.json, DS_Bronze_Estimates.json
adf/pipeline/PL_Vendor_Autobody_To_Bronze.json

scripts/deploy_adf.sh             # PUT every JSON to the factory, in dependency order
scripts/run_adf.sh 2026-10-16     # start a run, wait, print each activity
```

The folder layout is the one ADF's own Git integration writes. To change the
pipeline: edit the JSON (or change it in Studio and copy the `{}` code view
back into the file), run `deploy_adf.sh`, commit. Studio is for looking at
the canvas and for Monitor.

The sections below are the same pipeline built by hand in Studio, kept as a
guide to what each piece is.

**What the pipeline does**

```
landing/autobody/<date>/manifest.json ──► ReadManifest (Lookup)   "the vendor says N rows"
landing/autobody/<date>/repair_estimates.csv ──► CopyToBronze (Copy)
      ──► bronze/vendor/autobody/repair_estimates/year=/month=/day=/part-00000.csv
RowCountMatches (If Condition): rows copied == N ?
      yes ──► done
      no  ──► DeleteBadBronzeFile (Delete) ──► RowCountMismatch (Fail)
```

Why a manifest and not a Lookup count: Lookup returns at most 5,000 rows, so it
can't count a real file. Vendors send a control file with the count instead,
and the Copy activity reports `rowsCopied` for you to compare against.

**Expected numbers:** 16 Oct has **51** estimates. 17 Oct also has 51, and with
`--bad-manifest` its manifest claims **52**, which must fail.

Names below are the ones used in the exported JSON. Keep them exactly.

---

## 1. Open ADF Studio

Portal → resource group `polaris-rg` → the factory `polaris-adf-…` → **Launch
Studio**. The left bar: Home, **Author** (pencil), **Monitor** (gauge),
**Manage** (toolbox).

## 2. Linked service: how ADF reaches the storage account

Manage → Linked services → **+ New** → **Azure Data Lake Storage Gen2**.

| Field | Value |
|---|---|
| Name | `LS_ADLS_Polaris` |
| Authentication type | **System-assigned managed identity** |
| Account selection method | Enter manually |
| URL | `https://polaris599i8o.dfs.core.windows.net` |
| Test connection | **To file path**: `landing` |

Test connection to the whole account would fail with 403, and that's correct:
the factory only has roles on the `landing` and `bronze` containers, not the
account. Testing against `landing` proves the identity works.

Create.

## 3. Three datasets: pointers to files

Author → **+** → Dataset. For each, add the parameter first (Parameters tab),
then use it in the path with **Add dynamic content**.

**`DS_Landing_Manifest`**: Azure Data Lake Storage Gen2 → **JSON**
- Linked service `LS_ADLS_Polaris`, import schema **None**
- Parameter: `folder` (String)
- File path: file system `landing`, directory `@dataset().folder`, file `manifest.json`

**`DS_Landing_Estimates`**: ADLS Gen2 → **DelimitedText**
- Linked service `LS_ADLS_Polaris`, **First row as header ✓**, import schema **None**
- Parameter: `folder` (String)
- File path: `landing` / `@dataset().folder` / `repair_estimates.csv`

**`DS_Bronze_Estimates`**: ADLS Gen2 → **DelimitedText**
- Linked service `LS_ADLS_Polaris`, **First row as header ✓**, import schema **None**
- Parameter: `folder` (String)
- File path: `bronze` / `@dataset().folder` / `part-00000.csv`

Datasets are parameterised so one dataset serves every day. The pipeline
passes the folder in.

## 4. The pipeline

Author → **+** → Pipeline. Name: **`PL_Vendor_Autobody_To_Bronze`**.

Parameters tab (click empty canvas): **`ingest_date`**, String, default `2026-10-16`.

### 4a. `ReadManifest`: Lookup

General → Activities → **Lookup**. Name `ReadManifest`.
- Settings → Source dataset `DS_Landing_Manifest`
- `folder` = `@concat('autobody/', pipeline().parameters.ingest_date)`
- **First row only ✓**

### 4b. `CopyToBronze`: Copy data

Move & transform → **Copy data**. Name `CopyToBronze`. Drag the green
success arrow from `ReadManifest` onto it.
- Source → `DS_Landing_Estimates`, `folder` = `@concat('autobody/', pipeline().parameters.ingest_date)`
- Sink → `DS_Bronze_Estimates`, `folder` =

```
@concat('vendor/autobody/repair_estimates/year=', formatDateTime(pipeline().parameters.ingest_date, 'yyyy'), '/month=', formatDateTime(pipeline().parameters.ingest_date, 'MM'), '/day=', formatDateTime(pipeline().parameters.ingest_date, 'dd'))
```

That builds the same Hive-style layout as the rest of Bronze.

### 4c. `RowCountMatches`: If Condition

Iteration & conditionals → **If Condition**. Name `RowCountMatches`. Success
arrow from `CopyToBronze`.
- Expression:

```
@equals(activity('CopyToBronze').output.rowsCopied, activity('ReadManifest').output.firstRow.row_count)
```

- **True** branch: leave empty. The data is in Bronze.
- **False** branch (pencil icon), add two activities joined by a success arrow:
  1. General → **Delete**, name `DeleteBadBronzeFile`. Dataset
     `DS_Bronze_Estimates` with the same `folder` expression as the Copy sink.
     Logging settings: **Enable logging off**. A file that failed the check
     must not stay in Bronze looking valid.
  2. General → **Fail**, name `RowCountMismatch`.
     - Error code: `ROW_COUNT_MISMATCH`
     - Message:

```
@concat('Row count mismatch for ', pipeline().parameters.ingest_date, ': manifest says ', string(activity('ReadManifest').output.firstRow.row_count), ', copied ', string(activity('CopyToBronze').output.rowsCopied))
```

Click **Validate** (top). Expect "Your pipeline has been validated. No errors
were found."

## 5. Debug run, good day

Debug → `ingest_date` = `2026-10-16`. In the Output tab, expect:
- `ReadManifest` Succeeded. Output → `firstRow.row_count` = **51**
- `CopyToBronze` Succeeded. Details (glasses icon) → rows read **51**, rows
  written **51**
- `RowCountMatches` Succeeded, took the True branch

Then **Publish all**. Debug runs use your unsaved draft; triggers only see
what's published.

## 6. Debug run, bad manifest

Drop 17 Oct with a manifest that claims one row too many (the terminal command
is in chat). Debug with `ingest_date` = `2026-10-17`. Expect:
- `CopyToBronze` Succeeded, **51** rows
- `RowCountMatches` takes the **False** branch
- `DeleteBadBronzeFile` Succeeded
- `RowCountMismatch` **Failed**: *Row count mismatch for 2026-10-17: manifest
  says 52, copied 51*
- The pipeline run shows **Failed**, and nothing is left in Bronze for 17 Oct

## 7. Triggers: a look, not a schedule

Pipeline → Add trigger → New/Edit → **+ New**:
- **Schedule**: `TR_Daily_0600`, every 1 day at 06:00, timezone Eastern.
  Parameter `ingest_date` = `@formatDateTime(trigger().scheduledTime, 'yyyy-MM-dd')`.
  Set **Start trigger: No**, so nothing runs (or costs) on its own.
- Open **Storage events** too, and read what it needs (Event Grid, a blob path
  such as `autobody/` ending in `manifest.json`). Don't create it. It's the
  "run as soon as the vendor's manifest lands" option; Airflow takes the
  scheduling job in Stage 7.

Publish all.

## 8. Into git

Export with the command in chat: it downloads the linked service, datasets,
pipeline and trigger as JSON into `adf/`. The factory itself stays in
Terraform; the pipeline definition is now code too.

## What the first runs taught (20 Oct 2026)

1. **`quoteAllText: false` is rejected at run time** ("cannot set to false for
   Copy activity currently"), though the JSON schema allows it. Bronze CSVs
   from ADF quote every value.
2. **No `rowsCopied` on a plain CSV-to-CSV copy.** Same format on both sides
   and no column changes, so ADF copied the file byte for byte
   (`dataRead` = `dataWritten` = 3,739) and never counted rows. The If
   Condition then failed on a missing property. An empty column mapping
   didn't change that.
3. **Fix: `additionalColumns`** (`_source_file`, `_ingest_date`). Adding
   columns forces a row-by-row copy, so `rowsRead` / `rowsCopied` appear, and
   every Bronze row now says where and when it came from.
4. **Gap found:** when the If Condition itself errors (not evaluates to
   false), the Delete branch never runs and the copied file stays in Bronze.
   Candidate first ticket.

| Run | Result |
|---|---|
| 16 Oct | manifest 51, copied 51, check passed. Bronze file: 52 lines (51 + header) |
| 17 Oct, `--bad-manifest` | manifest 52, copied 51, `DeleteBadBronzeFile` ran, run **Failed**: *Row count mismatch for 2026-10-17: manifest says 52, copied 51*. Nothing left in Bronze for 17 Oct |

## Interview line

"In Polaris a vendor drops repair estimates and a manifest into a landing
container. An ADF pipeline, logging in with the factory's managed identity,
reads the manifest, copies the file into Bronze in the same date-partitioned
layout, and compares rows copied with the manifest's count. On a mismatch it
deletes what it copied and fails the run, so Bronze never holds a short file."

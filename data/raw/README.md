# Source data — how to obtain it

Neither dataset is redistributed in this repo. Both are public; download them into the
paths below and every notebook, the dbt project, and the dashboard build will run.

## 1. REES46 — eCommerce Events History in Cosmetics Shop

The primary dataset: 20.7M events, 1.64M users, Oct 2019 – Feb 2020.

- Source: <https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop>
- Licence: as stated on the Kaggle page (Open Data Commons; attribute REES46 Marketing Platform).

Download the five monthly CSVs and place them, unzipped and unrenamed, in `data/raw/`:

```
data/raw/2019-Oct.csv     482,542,278 bytes
data/raw/2019-Nov.csv     545,839,412 bytes
data/raw/2019-Dec.csv     415,302,972 bytes
data/raw/2020-Jan.csv     501,792,804 bytes
data/raw/2020-Feb.csv     488,799,986 bytes
```

With the Kaggle CLI:

```bash
kaggle datasets download -d mkechinov/ecommerce-events-history-in-cosmetics-shop -p data/raw
unzip -j data/raw/ecommerce-events-history-in-cosmetics-shop.zip -d data/raw
```

Schema: `event_time, event_type, product_id, category_id, category_code, brand, price,
user_id, user_session`. There is no `order_id` — orders are reconstructed, and the
reconstruction rule is derived and certified in `notebooks/00_data_quality.ipynb`
(recorded in `outputs/handoff_params.json → order_reconstruction`).

Note: `user_id` is cookie-scoped, not account-scoped. Every retention and repeat-purchase
figure in this project is a lower bound on true customer-level behaviour.

## 2. Criteo Uplift Prediction dataset (v2.1)

A genuine randomized incrementality test, 13,979,592 rows. Used only in
`notebooks/07_criteo_experiment.ipynb`, to validate the experiment-analysis methodology
and the risk-vs-uplift targeting argument.

- Direct download (Criteo AI Lab's Azure mirror):
  <https://criteostorage.blob.core.windows.net/criteo-research-datasets/criteo-uplift-v2.1.csv.gz>
- Dataset page: <https://ailab.criteo.com/criteo-uplift-prediction-dataset/>
- The canonical `go.criteo.net` link now 404s. A Hugging Face mirror
  (`datasets/criteo/criteo-uplift`) serves a byte-identical file.

```bash
mkdir -p data/raw/criteo
curl -L -o data/raw/criteo/criteo-research-uplift-v2.1.csv.gz \
  https://criteostorage.blob.core.windows.net/criteo-research-datasets/criteo-uplift-v2.1.csv.gz
```

Expected file:

```
data/raw/criteo/criteo-research-uplift-v2.1.csv.gz    311,422,618 bytes
sha256  2716e1bf0fd157a93b5bf86924d9088419dfbac2022c6cd90030220634f616dc
```

That digest was recorded from the file used here, not published by Criteo. It pins the
bytes across runs; it is not evidence of provenance.

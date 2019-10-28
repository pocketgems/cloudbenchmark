# Running the benchmarks

This will take several hours to deploy and up to a day to run (testing CR and
GKE is the slowest part by far right now due to its sequential test
running). Remember to delete the project when you're done testing. Testing will
likely cost at least many hundreds of dollars.

1. Create a new GCP project where you'll run the test. Enable billing!
1. Run `./setup.sh "PROJECT_NAME_HERE"` (you'll be prompted to sign in, and then
   the script will deploy a bunch of services, etc.).
1. Compute deployment stats: `./platform/aggregate_deploy_times.py`
1. Run the benchmarks:
    * Run GAE and CR Managed tests (except json): `./benchmark/run.py "PROJECT_NAME_HERE" -n5 --secs 180 --continue data.json --filter '^(py37|py38|node10|node12|managed)' --test all`
    * Run GAE and CR Managed json test: `./benchmark/run.py "PROJECT_NAME_HERE" -n5 --secs 180 --continue data.json --filter '^(py37|py38|node10|node12|managed)' --test json`
    * Run CR on GKE tests (except json): `./benchmark/run.py "PROJECT_NAME_HERE" -n5 --secs 180 --continue data-gke.json --filter highcpu --test all --sequential`
    * GKE tests are run separately from other tests because they need to be run sequentially to avoid blowing up a small GKE cluster right now.
    * Run CR on GKE json test: `./benchmark/run.py "PROJECT_NAME_HERE" -n5 --secs 180 --continue data-gke.json --filter highcpu --test json --sequential`
1. Compute benchmark stats: `./platform/evaluate_aggregate_results.py data.json data-gke.json`
    * If some data points are too noisy, you'll see output suggesting you collect more data. The output will have a command you can copy/paste to run more benchmarks.

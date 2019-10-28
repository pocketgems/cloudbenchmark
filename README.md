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


# Project structure

  * The `platforms` folder contains the code being benchmarked. There are
    implementations for each test in both JavaScript and
    Python. Implementations cover GAE Standard v1 and v2, as well as Cloud Run
    Managed and on Athos. Many copies are deployed so that many tests can be
    run in parallel. There are also many permutations to test various
    configurations. Deployed services are configured to only allow a single
    instance so we can benchmark per-instance performance (not the services
    ability to scale).

  * The `benchmark` folder contains code for running and aggregating
    performance measurements. Performance is measured by a Cloud Function
    running the same region (and, for all tests possible, the same zone). Many
    instances of the cloud functions are invoked in parallel to test different
    services.


# Tests

  * `noop` - the server merely responds with an HTTP 200. This is intended to
    measure overhead in serving requests from each framework, runtime and
    platform.

  * `sleep` - the server sleeps for one second before replying. This measures
    the ability to servce as many concurrent connections as possible (up to the
    limit of 80 imposed by both GAE and Cloud Run).

  * `data` - the server returns 1MB of uncompressed data in the HTTP
    response. This tests network throughput.

  * `memcache` - the server does some basic memcache data gets and sets. GAE
    memcache is used for GAE v1, and Cloud Memorystore (Redis) is used for
    everything else. This measures the performance of both the in-memory
    key-value store as well as overhead in communicating with it.

  * `json` - the server serializes and then deserializes a very large (~1.5MB
    in string form) JSON blob that is representative of a very advanced player
    in one of our games.

  * `dbjson` - same as `json`, but the server also zlib compresses and
    decompresses the JSON data, and stores and loads this comrpessed data from
    the datastore.


  * `dbtx` - does 5 datastore transactions which increment a random small
    datastore entity (get nonexistant entity, then create it) (does the 5
    transactions one after another).


  * `dbindir` - gets a small datastore entity and then gets another small
    datastore entity which depends on what value is in the first one. Does
    three of these in parallel.

  * `dbindirb` - like `dbindir`, except it changes how it parallelizes the
    work. It first gets all of the entities required in step 1 in one
    synchronous batch, and then all of the entities required in step 2 in a
    second batch.

  * `txtask` - does a database transaction which also enqueues a task which is
    executed if and only if the transaction commits. The task runtime is not
    part of the benchmark (only creating it). Only GAE v1 natively supports
    this. All other platforms use a custom implementation.

  * For tests involving the datastore, the GAE v2 Python 3 runtime tests
    evaluate both google-cloud-datastore from PyPi as well as Google's ndb
    library.

  * On GAE v1, instance classes F1, F2 and F4 are each benchmarked. On GAE v2,
    only F1 is benchmarked.

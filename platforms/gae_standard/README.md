# Running the benchmarks

1. Create a new GCP project where you'll run the test. Enable billing!
2. Run `./init.sh "PROJECT_NAME_HERE"` (you'll be prompted to sign in, and then
   the script will deploy a bunch of services, etc.).
3. Run the benchmarking script in benchmark/benchmark.js. You will need node v10 installed. This should ideally be run from a GCE instance in your project and in the same region as your applications to minimize latency from the (unpredictable) public internet. Use like: `./benchmark.js PROJECT_NAME_HERE TEST_NAME_HERE 300s`

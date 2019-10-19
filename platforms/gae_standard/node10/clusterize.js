exports.startApp = (startApp) => {
    const PORT = process.env.PORT || 8080;
    const NUM_CORES = +process.env.NUM_CORES || 1;
    if (NUM_CORES > 1) {
        const cluster = require('cluster');
        if(cluster.isMaster) {
            for(let i = 0; i < NUM_CORES; i++) {
                cluster.fork();
            }
            cluster.on('exit', function(worker, code, signal) {
                console.error(['worker PID ', worker.process.pid,
                               ' died (code=', code, ' signal=', signal,
                               ' (starting new worker)'].join(''));
                cluster.fork();
            });
        }
        else {
            startApp(PORT);
        }
    }
    else {
        startApp(PORT);
    }
};

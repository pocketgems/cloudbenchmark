const util = require('util');
const uuidv4 = require('uuid/v4');
const zlib = require('zlib');
const deflate = util.promisify(zlib.deflate);
const inflate = util.promisify(zlib.inflate);

const APP_ID = (process.env.GAE_APPLICATION || '').replace('s~', '');

const {Datastore} = require('@google-cloud/datastore');
const dbc = new Datastore();

const {CloudTasksClient} = require('@google-cloud/tasks');
const taskqcfg = process.env.GOOGLE_APPLICATION_CREDENTIALS ? undefined : {
    keyFilename: 'cloudtasksaccount.json'
};
const taskq = new CloudTasksClient(taskqcfg);

const rcache = (process.env.REDIS_HOST ? require('async-redis').createClient({
    host: process.env.REDIS_HOST,
    port: +process.env.REDIS_PORT,
}) : null);
if (rcache) {
    rcache.on('error', err => console.error('Redis Error:', err));
}
else {
    console.log('rcache env vars not supplied');
}

exports.sleep = (secs) => {
    return new Promise(replyolve => {
        setTimeout(replyolve, secs * 1000);
    });
};

exports.doMemcache = async (n, sz) => {
    const key = uuidv4();
    const val = 'x'.repeat(sz);
    await rcache.set(key, val, 'EX', 60);
    for (let i = 0; i < n; i++) {
        const ret = await rcache.get(key);
        if (ret !== val) {
            console.log('value from cache=', ret);
            console.log('value expected=', val);
            throw new Error('value in cache is wrong');
        }
    }
}

exports.doDatastoreTx = async (n) => {
    const randomID = uuidv4();
    for (let i = 0; i < n; i++) {
        const tx = dbc.transaction();
        await tx.run();
        const counter = await incrDbEntry(tx, randomID);
        tx.save(counter);
        await tx.commit();
    }
}

exports.doTxTask = async (n) => {
    for (let i = 0; i < n; i++) {
        const txID = uuidv4();
        const fqQueueName = taskq.queuePath(APP_ID, 'us-central1', 'testpy3');
        const task = {
            appEngineHttpRequest: {
                httpMethod: 'POST',
                relativeUri: '/handleTxTask',
                body: 'x'.repeat(512).toString('base64'),
                appEngineRouting: {
                    service: 'py3',  // to py3 since not testing its perf
                    version: 'txtaskhandler',
                },
                headers: {
                    TXID: txID,
                },
            },
        };
        const request = {
            parent: fqQueueName,
            task: task,
        };

        // we MUST ensure our task has been created before we can commit our tx
        // BUT we don't have to block on it yet; we can queue up other db API
        // calls first
        let taskFuture = taskq.createTask(request);
        try {
            const randomID = uuidv4();
            const tx = dbc.transaction();
            await tx.run();
            const counter = await incrDbEntry(tx, randomID);
            const txDoneSentinel = {
                key: dbc.key(['JSTxDoneSentinel', txID]),
                data: {}
            };
            await tx.save([counter, txDoneSentinel]);
            const [response] = await taskFuture;
            const taskName = response.name;
            await tx.commit();
        }
        catch (err) {
            taskq.deleteTask({name: taskName});
            throw err;
        }
    }
};

async function incrDbEntry(tx, someID) {
    // tries to get a db entity which won't exist and then creates it
    const key = dbc.key(['JSCounter', someID]);
    let [data] = await tx.get(key);
    if (!data) {
        data = [{
            name: 'count',
            value: 1,
            excludeFromIndexes: true
        }];
    }
    else {
        // we can't simply increment the value in-place because the returned
        // data doesn't include the excludeFromIndexes info; we must set it
        // with save() or our field will get indexed :(
        data = [{
            name: 'count',
            value: data.count + 1,
            excludeFromIndexes: true
        }];
    }
    return {
        key: key,
        data: data
    };
}

var bigJson = undefined;
exports.doDbJson = async (jsonOnly) => {
    if (!bigJson) {
        const fs = require('fs');
        bigJson = JSON.parse(fs.readFileSync('big.json', 'utf8'));
        throw new Error('read from file');  // don't include in benchmark
    }
    if (jsonOnly) {
        JSON.parse(JSON.stringify(bigJson));
        return 'did json only';
    }

    const randomID = uuidv4();
    const key = dbc.key(['BigJsonHolder', randomID]);
    const val = await deflate(JSON.stringify(bigJson));
    await dbc.save({
        key: key,
        data: [{
            name: 'data',
            value: val,
            excludeFromIndexes: true
        }]
    });
    const [entity] = await dbc.get(key);
    const input = entity.data;
    const data = await inflate(input);
    JSON.parse(data);
    return data.length.toString();
};

function getRandomKey() {
    const randomInt = Math.floor(Math.random() * 10000);
    return dbc.key(['OneInt', randomInt]);
}
exports.doDbIndir = async (n) => {
    const promises = [];
    for (var i = 0; i < n; i++) {
        promises.push(getAndThenGetDependency());
    }
    const results = await Promise.all(promises);
    var ret = 0;
    results.forEach(v => { ret += v; });
    return ret.toString();
};
async function getAndThenGetDependency() {
    const [x] = await dbc.get(getRandomKey());
    if (!x) {
        throw new Error('OneInt entity missing (not yet defined?)');
    }
    const keyID = +(x[dbc.KEY].path[1]);
    const newID = (2 * keyID) % 10000;
    const subkey = dbc.key(['OneInt', newID]);
    const [subx] = await dbc.get(subkey);
    const subID = +(subx[dbc.KEY].path[1]);
    return subID + newID;
}

exports.doDbIndirb = async (n) => {
    const keys = [];
    for (var i = 0; i < n; i++) {
        keys.push(getRandomKey());
    }
    const [entities] = await dbc.get(keys);
    if (entities.indexOf(undefined) !== -1) {
        throw new Error('OneInt entity missing (not yet defined?)');
    }
    const newKeys = [];
    entities.forEach(entity => {
        const keyID = entity[dbc.KEY].path[1];
        newKeys.push(dbc.key(['OneInt', (2 * keyID) % 10000]));
    });
    const [newEntities] = await dbc.get(newKeys);
    entities.push(...newEntities);
    var sum = 0;
    entities.forEach(v => { sum += (+v[dbc.KEY].path[1]); });
    return sum.toString();
};

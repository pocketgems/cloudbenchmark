const util = require('util');
const uuidv4 = require('uuid/v4');

const APP_ID = (process.env.GAE_APPLICATION || '').replace('s~', '');

const {Spanner} = require('@google-cloud/spanner');
const spanner = new Spanner();
const instance = spanner.instance('default');
const db = instance.database('default');

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
    return new Promise(resolve => {
        setTimeout(resolve, secs * 1000);
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
        await db.runTransactionAsync(async (tx) => {
            await incrDbEntry(tx, randomID)
                .then(() => tx.commit())
                .then(()=> tx.end())
        })
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
        const randomID = uuidv4();
        await db.runTransactionAsync(async (tx) => {
            const counter = incrDbEntry(tx, randomID);
            await counter.then(async () => {
                tx.insert('JSTxDoneSentinel', {
                    id: txID
                })
                await taskFuture
            })
                .then(() => tx.commit())
                .then(() => tx.end())
        }).catch(async err => {
            const [response] = await taskFuture;
            const taskName = response.name;
            taskq.deleteTask({name: taskName});
            throw err;
        })
    }
};

async function incrDbEntry(tx, someID) {
    // tries to get a db entity which won't exist and then creates it
    return tx.read('JSCounter', {
        columns: ['id', 'count'],
        keys: [someID],
        json: true
    }).then(data => {
        /**
         * If someID doesn't exists, data will be 
         * [ [] ]
         * 
         * If someID exists, and json: false, data is
         * [ [ {name: 'id', value: someID}, {name: 'count', value: 1} ] ]
         * 
         * If someID exists, and json: true, data is
         * [ [ {id: someID, count: 1} ] ]
         */
        data = data[0]
        if (data.length === 0) {
            data = {id: someID, count: 1}
        } else {
            data = data[0]
            data.count += 1
        }

        /**
         * upsert takes row (object) or array of rows (objects)
         */
        return tx.upsert('JSCounter', data)
    })
}

const fs = require('fs');
const bigJson = JSON.parse(fs.readFileSync('big.json', 'utf8'));

exports.doDbJson = async (jsonOnly) => {
    if (jsonOnly) {
        JSON.parse(JSON.stringify(bigJson));
        return 'did json only';
    }

    const randomID = uuidv4();
    const val = JSON.stringify(bigJson);
    const table = db.table('BigJsonHolder')
    await table.upsert({
        id: randomID,
        data: val
    })

    let [data] = await table.read({
        keys: [randomID],
        columns: ['data'],
        json: true
    })
    data = data[0].data
    JSON.parse(data);
    return data.length.toString();
};

function getRandomKey() {
    return Math.floor(Math.random() * 10000);
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
    const table = db.table('OneInt')
    const [x] = await table.read({
        keys: [getRandomKey()],
        columns: ['id'],
        json: true
    })
    if (x.length === 0) {
        throw new Error('OneInt entity missing (not yet defined?)');
    }
    const keyID = +(x[0].id);
    const newID = (2 * keyID) % 10000;
    const [subx] = await table.read({
        keys: [newID],
        columns: ['id'],
        json: true
    })
    const subID = +(subx[0].id);
    return subID + newID;
}

exports.doDbIndirb = async (n) => {
    const keys = [];
    for (var i = 0; i < n; i++) {
        keys.push(getRandomKey());
    }

    const table = db.table('OneInt')
    const [entities] = await table.read({
        keys: keys,
        columns: ['id'],
        json: true
    })
    if (entities.indexOf(undefined) !== -1) {
        throw new Error('OneInt entity missing (not yet defined?)');
    }
    const newKeys = entities.map(entity => {
        return Math.trunc((2 * entity.id) % 10000);
    });
    const [newEntities] = await table.read({
        keys: newKeys,
        columns: ['id'],
        json: true
    })
    entities.push(...newEntities);
    var sum = 0;
    entities.forEach(v => { sum += (+v.id); });
    return sum.toString();
};

const uuidv4 = require('uuid/v4');

const APP_ID = (process.env.GAE_APPLICATION || '').replace('s~', '');

const {Datastore} = require('@google-cloud/datastore');
const dbc = new Datastore();

const {CloudTasksClient} = require('@google-cloud/tasks');
const taskq = new CloudTasksClient({keyFilename: 'cloudtasksaccount.json'});

if (process.env.REDIS_HOST) {
    const rcache = require('redis').createClient({
        host: process.env.REDIS_HOST,
        port: process.env.REDIS_PORT,
    });
}
else {
    console.log('missing redis creds');
    const rcache = null;
}

exports.doMemcache = async (n, sz) => {
    const key = uuidv4();
    const val = 'x'.repeat(sz);
    await rcache.set(key, val, 'EX', 60);
    for (let i = 0; i < n; i++) {
        const ret = await rcache.get(key);
        if (ret !== val) {
            throw new Error('value in cache is wrong');
        }
    }
}

exports.doDatastoreTx = async (n) => {
    const randomID = uuidv4();
    for (let i = 0; i < n; i++) {
        const tx = await dbc.transaction();
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
            const tx = await dbc.transaction();
            await tx.run();
            const counter = await incrDbEntry(tx, randomID);
            const txDoneSentinel = {
                key: dbc.key(['JSTxDoneSentinel', txID]),
                data: {}
            };
            await tx.save([counter, txDoneSentinel]);
            const [response] = await taskFuture;
            const taskName = response.name;
            console.log(`Created task ${taskName}`);
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

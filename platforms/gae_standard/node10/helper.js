const uuidv4 = require('uuid/v4');

const APP_ID = (process.env.GAE_APPLICATION || '').replace('s~', '');

const {Datastore} = require('@google-cloud/datastore');
const dbc = new Datastore();

const {CloudTasksClient} = require('@google-cloud/tasks');
const client = new CloudTasksClient({keyFilename: 'cloudtaskaccount.json'});

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

function do_memcache(n, sz, cb) {
    const key = uuidv4();
    const val = 'x'.repeat(sz);
    rcache.set(key, val, 'EX', 60, (err) => {
        if (err) {
            cb(err);
            return;
        }
        let i = 0;
        function doGet() {
            rcache.get(key, (err, ret) => {
                if (err) {
                    cb(err);
                    return;
                }
                if (ret !== val) {
                    cb(new Error('value in cache is wrong'));
                }
                i += 1;
                if (i < n) {
                    doGet();
                }
                else {
                    cb();  // all done
                }
            });
        }
        doGet();
    });
}

async function do_db_tx(n) {
    for (let i = 0; i < n; i++) {
        const randomID = uuidv4();
        const tx = await dbc.transaction();
        await tx.run();
        const entity = await incr_db_entry(tx, randomID);
        await tx.commit();
    });
}

function do_tx_task(n) {
    for ignore in range(n):
        tx_id = uuid.uuid4().hex
        fq_queue_name = taskq.queue_path(
            APP_ID,
            'us-central1',
            'testpy3')  # this is the queue name
        task = dict(
            app_engine_http_request=dict(
                http_method='POST',
                relative_uri='/handleTxTask',
                body=('x' * 512).encode(),  # encode to bytes
                app_engine_routing=dict(
                    service='py3',
                    version='txtaskhandler',
                ),
                headers=dict(
                    TXID=tx_id,
                ),
            ),
        )
        new_task = taskq.create_task(fq_queue_name, task)
        random_id = uuid.uuid4().hex
        try:
            with dbc.transaction():
                counter = incr_db_entry(random_id)
                tx_done_sentinel = db.Entity(key=dbc.key('TxDoneSentinel',
                                                         tx_id))
                dbc.put_multi([counter, tx_done_sentinel])
        except:
            taskq.delete_task(new_task['name'])
}

async function incr_db_entry(tx, someID) {
    // tries to get a db entity which won't exist and then creates it
    const key = dbc.key(['Counter', someID]);
    let [x] = await tx.get(key);
    if (!x) {
        x = {
            key: key,
            data: {count: 0}
            /*
            [{
                name: 'count',
                value: 0,
                excludeFromIndexes: true
            }]
            */
        };
    }
    tmpx=x;
    //x.data['count'] += 1;
    tx.save(x);
    return x;
}
async function test(id) {
    const tx = await dbc.transaction();
    await tx.run();
    const entity = await incr_db_entry(tx, id);
    await tx.commit();
    return entity;
}
test('atest1').then((entity) => { tmp = entity; });

const fs = require('fs');
const uuidv4 = require('uuid/v4');

const bigJson = JSON.parse(fs.readFileSync('big.json', 'utf8'));

var AWS = require('aws-sdk');
AWS.config.loadFromPath('./creds.json');
var db = new AWS.DynamoDB.DocumentClient({apiVersion: '2012-08-10'});


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
        const counter = await txIncrDbEntry(randomID);
    }
}

exports.doTxTask = async (n) => {
    throw new Error('txtask is not yet implemented');
};

async function txIncrDbEntry(someID) {
    // DynamoDB can actually do this in a single updateItem API call!  However,
    // this test is trying to measure a transactional update which REQUIRES
    // computation beyond what can be done with DynamoDB update expressions.
    // So we first fetch the data, and then modify it. To this transactionally
    // with DynamoDB, we need to keep a version number attribute (to ensure our
    // update takes place if and only if nobody modifies the data we read).


    // tries to get a db entity which may not exist
    //dbc.key(['JSCounter', someID]);
    const key = {id: someID};
    var item = (await db.get({
        TableName: 'JSCounter',
        ConsistentRead: true,
        Key: {
            id: someID,
        }
    }).promise()).Item;

    const putParams = {
        TableName: 'JSCounter',
    };
    if (!item) {
        putParams.ConditionExpression = 'attribute_not_exists(id)';
        putParams.Item = {
            id: someID,
            count: 1,
            ver: 1
        };
    }
    else {
        putParams.ConditionExpression = 'ver = :prevVer';
        putParams.ExpressionAttributeValues = {':prevVer': item.ver};
        putParams.Item = item;
        item.count += 1;
        item.ver += 1;
    }
    await db.transactWrite({TransactItems: [{ Put: putParams }]}).promise();
}

exports.doDbJson = async (jsonOnly) => {
    if (jsonOnly) {
        JSON.parse(JSON.stringify(bigJson));
        return 'did json only';
    }

    const randomID = uuidv4();
    const val = JSON.stringify(bigJson);
    await db.put({
        TableName: 'BigJsonHolder',
        Item: {
            id: randomID,
            data: val
        }
    }).promise();
    const resp = await db.get({
        TableName: 'BigJsonHolder',
        ConsistentRead: true,
        Key: {
            id: randomID
        }
    }).promise();
    const data = resp.Item.data;
    JSON.parse(data);
    return data.length.toString();
};

function getRandomKey() {
    const randomInt = Math.floor(Math.random() * 10000);
    return { id: randomInt };
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
    const x = (await db.get({
        TableName: 'OneInt',
        ConsistentRead: true,
        Key: getRandomKey()
    }).promise()).Item;
    if (!x) {
        throw new Error('OneInt entity missing (not yet defined?)');
    }
    const keyID = x.id;
    const newID = (2 * keyID) % 10000;
    const subkey = {id: newID};
    const subx = (await db.get({
        TableName: 'OneInt',
        ConsistentRead: true,
        Key: subkey
    }).promise()).Item;
    const subID = subx.id;
    return subID + newID;
}

exports.doDbIndirb = async (n) => {
    const keys = [];
    for (var i = 0; i < n; i++) {
        keys.push(getRandomKey());
    }
    const entities = (await db.batchGet({
        RequestItems: {
            OneInt: {
                ConsistentRead: true,
                Keys: keys
            }
        }
    }).promise()).Responses.OneInt;
    if (entities.length !== keys.length) {
        throw new Error('OneInt entity missing (not yet defined?)');
    }
    const newKeys = [];
    entities.forEach(entity => {
        const keyID = +entity.id;
        newKeys.push({ id: (2 * keyID) % 10000});
    });
    const newEntities = (await db.batchGet({
        RequestItems: {
            OneInt: {
                ConsistentRead: true,
                Keys: newKeys
            }
        }
    }).promise()).Responses.OneInt;
    if (newEntities.length !== newKeys.length) {
        throw new Error('OneInt entity missing (not yet defined?)');
    }
    entities.push(...newEntities);
    var sum = 0;
    entities.forEach(v => { sum += v.id; });
    return sum.toString();
};

# manual steps to do first:
#  1) setup AWS client with root credentials (an organization account)
#  2) setup AWS service account with full DynamoDB access; make creds.json with
#     its access id/key and the region we want to test in

tableNames=('JSCounter' 'BigJsonHolder' 'OneInt')
for idx in `seq 2 2`; do
    if [ $idx -eq 2 ]; then
        # numeric primary key for the OneInt table
        type=N
    else
        type=S
    fi
    aws dynamodb create-table --table-name ${tableNames[$idx]} --key-schema AttributeName=id,KeyType=HASH --attribute-definitions AttributeName=id,AttributeType=${type} --billing-mode PAY_PER_REQUEST
done

for idx in `seq 0 9999`; do
    if [ $idx -ne 0 ]; then
        echo "   $idx done"
    fi
    aws dynamodb put-item --table-name OneInt --item "{\"id\":{\"N\":\"${idx}\"}}"
done

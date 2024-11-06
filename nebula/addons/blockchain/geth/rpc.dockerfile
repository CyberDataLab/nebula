FROM ethereum/client-go:alltools-v1.13.10

ENV address=""
ENV bootnodeId=""
ENV bootnodeIp=""

COPY ./genesis.json ./genesis.json
RUN geth init genesis.json
RUN rm -f ~/.ethereum/geth/nodekey

CMD exec geth \
    --bootnodes "enode://$bootnodeId@$bootnodeIp:30301" \
    --http \
    --http.addr="0.0.0.0" \
    --http.api="eth,web3,net,admin,personal" \
    --http.corsdomain="*" \
    --networkid=19265019 \
    --http.vhosts="*" \
    --allow-insecure-unlock \
    --http.port=8545 \
    --rpc.txfeecap 0

EXPOSE 8545

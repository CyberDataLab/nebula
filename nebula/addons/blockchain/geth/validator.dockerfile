FROM ethereum/client-go:alltools-v1.13.14

ARG password
ARG privatekey

ENV address=""
ENV bootnodeId=""
ENV bootnodeIp=""
ENV port=""

COPY ./genesis.json ./genesis.json
RUN geth init genesis.json
RUN rm -f ~/.ethereum/geth/nodekey

RUN echo $password > ~/.accountpassword
RUN echo $privatekey > ~/.privatekey
RUN geth account import \
    --password ~/.accountpassword  ~/.privatekey

CMD exec geth \
    --port $port \
    --bootnodes "enode://$bootnodeId@$bootnodeIp:30301" \
    --networkid=19265019 \
    --mine \
    --miner.etherbase $address \
    --unlock $address \
    --password ~/.accountpassword \
    --netrestrict="172.25.0.0/24"

EXPOSE $port

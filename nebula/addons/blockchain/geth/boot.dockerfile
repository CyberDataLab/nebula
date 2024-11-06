FROM ethereum/client-go:alltools-v1.13.10

ENV nodekeyhex=""

CMD exec bootnode \
    -nodekeyhex $nodekeyhex \
    --netrestrict="172.25.0.0/24"

EXPOSE 30301/udp
EXPOSE 30303/tcp
EXPOSE 8081

import os, json, random
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
random.seed(7)
out=[]
for i in range(300):
    key=os.urandom(32); nonce=os.urandom(12)
    n=random.choice([0,1,15,16,17,31,32,33,63,64,65,100,255,1000,4096])+ (i%3)
    pt=os.urandom(n); aad=os.urandom(random.choice([0,1,5,16,17,40]))
    ct=ChaCha20Poly1305(key).encrypt(nonce,pt,aad)
    out.append(dict(key=key.hex(),nonce=nonce.hex(),pt=pt.hex(),aad=aad.hex(),ct=ct.hex()))
# poly1305 all-ones / edge-ish keys: key with max r, long messages of 0xff
for k in (b'\xff'*32, b'\x00'*32):
    for n in (16,32,48,1000):
        key=k;nonce=b'\x00'*12;pt=b'\xff'*n
        out.append(dict(key=key.hex(),nonce=nonce.hex(),pt=pt.hex(),aad="",ct=ChaCha20Poly1305(key).encrypt(nonce,pt,b"").hex()))
json.dump(out,open("testdata/chacha_vectors.json","w"))
print(len(out))

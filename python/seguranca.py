import hashlib
import secrets
import os

import config
minha_senha = config.SENHA_SALVA.encode('utf-8')
salt_base_bytes = os.urandom(16)

hash_salvo = hashlib.scrypt(minha_senha, salt=salt_base_bytes, n=16384, r=8, p=1)

def validar_senha(senha_digitada: str) -> bool:
    hash_tentativa = hashlib.scrypt(
        senha_digitada.encode('utf-8'),
        salt=salt_base_bytes,
        n=16384, r=8, p=1
    )

    return secrets.compare_digest(hash_tentativa, hash_salvo)
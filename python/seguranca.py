import hashlib
import secrets

import config

salt_base_bytes = config.SALT_SALVO
hash_salvo = config.HASH_SALVO

"""
    n = quantidade de iterações que a CPU vai fazer
    r = tamanho do bloco de memoria sequencial que vai ser utilizado
    p = quantidade de threads podem rodar para executar o hash
"""

def validar_senha(senha_digitada: str) -> bool:
    hash_tentativa = hashlib.scrypt(
        senha_digitada.encode('utf-8'),
        salt=salt_base_bytes,
        n=16384, r=8, p=1
    )

    return secrets.compare_digest(hash_tentativa, hash_salvo)
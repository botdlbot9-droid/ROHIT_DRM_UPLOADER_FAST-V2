# modules/decryption_utils.py
import json
import base64
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Util.Padding import unpad
import hashlib

async def decrypt_auth_string(encrypted_base64: str) -> dict:
    """
    Decrypts the AES-256-CBC encrypted auth string.
    Returns a dictionary containing 'token' and 'randomId'.
    """
    password = 'DDMM6767YYCC'
    try:
        # 1. Base64 Decode
        encrypted_data = base64.b64decode(encrypted_base64)
        
        # 2. Extract Salt, IV, and Ciphertext
        salt = encrypted_data[:16]
        iv = encrypted_data[16:32]
        ciphertext = encrypted_data[32:]
        
        # 3. Derive Key using PBKDF2 (Same as HTML dashboard)
        key = PBKDF2(password, salt, dkLen=32, count=100000, hmac_hash_module=hashlib.sha256)
        
        # 4. Decrypt
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted_padded = cipher.decrypt(ciphertext)
        decrypted = unpad(decrypted_padded, AES.block_size)
        
        # 5. Parse JSON data
        data = json.loads(decrypted.decode('utf-8'))
        
        # Return the expected fields (adjust if your JSON has different keys)
        return {
            'token': data.get('testItem1'),
            'randomId': data.get('testItem3')
        }
    except Exception as e:
        raise ValueError(f"Decryption failed: {str(e)}")

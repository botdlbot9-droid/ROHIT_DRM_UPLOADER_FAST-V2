# modules/decryption_utils.py
import json
import base64
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Util.Padding import unpad
import hashlib
import re
import hmac

async def decrypt_auth_string(encrypted_base64: str) -> dict:
    """
    Decrypts the AES-256-CBC encrypted auth string.
    Returns a dictionary containing 'token' and 'randomId'.
    """
    password = 'DDMM6767YYCC'
    
    try:
        # ============================================================
        #  STEP 1: Clean the Auth String
        # ============================================================
        encrypted_base64 = re.sub(r'\s+', '', encrypted_base64)
        encrypted_base64 = encrypted_base64.replace('-', '+').replace('_', '/')
        
        # Add proper Base64 padding
        missing_padding = len(encrypted_base64) % 4
        if missing_padding:
            encrypted_base64 += '=' * (4 - missing_padding)
        
        print(f"🔑 Auth String (cleaned): {encrypted_base64[:50]}...")
        
        # ============================================================
        #  STEP 2: Decode Base64
        # ============================================================
        try:
            encrypted_data = base64.b64decode(encrypted_base64)
        except Exception as e:
            try:
                encrypted_data = base64.urlsafe_b64decode(encrypted_base64)
            except Exception as e2:
                raise ValueError(f"Base64 decode failed: {str(e2)}")
        
        print(f"📦 Decoded data length: {len(encrypted_data)} bytes")
        
        # ============================================================
        #  STEP 3: Extract Salt, IV, and Ciphertext
        # ============================================================
        if len(encrypted_data) < 48:
            raise ValueError(f"Data too short: {len(encrypted_data)} bytes. Expected at least 48.")
        
        salt = encrypted_data[:16]
        iv = encrypted_data[16:32]
        ciphertext = encrypted_data[32:]
        
        print(f"🧂 Salt: {salt.hex()[:16]}...")
        print(f"🔑 IV: {iv.hex()[:16]}...")
        print(f"📄 Ciphertext length: {len(ciphertext)} bytes")
        
        # ============================================================
        #  STEP 4: Derive Key using PBKDF2 (Python 3.12+ compatible)
        # ============================================================
        key = await derive_key_async(password, salt)
        
        print(f"🔐 Key derived: {key.hex()[:16]}...")
        
        # ============================================================
        #  STEP 5: Decrypt
        # ============================================================
        try:
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted_padded = cipher.decrypt(ciphertext)
        except Exception as e:
            raise ValueError(f"AES decryption failed: {str(e)}")
        
        # ============================================================
        #  STEP 6: Unpad
        # ============================================================
        try:
            decrypted = unpad(decrypted_padded, AES.block_size)
        except ValueError:
            try:
                pad_len = decrypted_padded[-1]
                if pad_len < AES.block_size:
                    decrypted = decrypted_padded[:-pad_len]
                else:
                    raise ValueError("Invalid padding")
            except Exception as e2:
                raise ValueError(f"Unpadding failed: {str(e2)}")
        
        print(f"✅ Decrypted data length: {len(decrypted)} bytes")
        
        # ============================================================
        #  STEP 7: Parse JSON
        # ============================================================
        try:
            decrypted_text = decrypted.decode('utf-8')
            print(f"📝 Decrypted text: {decrypted_text[:100]}...")
            data = json.loads(decrypted_text)
        except UnicodeDecodeError as e:
            raise ValueError(f"UTF-8 decode failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON parse failed: {str(e)}")
        
        # ============================================================
        #  STEP 8: Extract required fields
        # ============================================================
        token = data.get('testItem1')
        random_id = data.get('testItem3')
        
        if not token:
            raise ValueError("Missing 'testItem1' (token) in decrypted data")
        if not random_id:
            raise ValueError("Missing 'testItem3' (randomId) in decrypted data")
        
        print(f"✅ Token: {token[:20]}...")
        print(f"✅ RandomId: {random_id[:20]}...")
        
        return {
            'token': token,
            'randomId': random_id
        }
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Decryption error: {error_msg}")
        print(f"❌ Auth String (first 100 chars): {encrypted_base64[:100]}...")
        raise ValueError(f"Decryption failed: {error_msg}")


# ============================================================
#  🔥 ASYNC KEY DERIVATION FUNCTION (Python 3.12+ compatible)
# ============================================================
async def derive_key_async(password: str, salt: bytes) -> bytes:
    """
    Derives a 32-byte AES key using PBKDF2 with HMAC-SHA256.
    Compatible with Python 3.10, 3.11, and 3.12+.
    """
    # Method 1: Try using hashlib.sha256 directly (works in most versions)
    try:
        key = PBKDF2(password, salt, dkLen=32, count=100000, hmac_hash_module=hashlib.sha256)
        print("✅ PBKDF2: Using hashlib.sha256")
        return key
    except AttributeError:
        pass
    
    # Method 2: Try using hashlib.sha256() as a callable
    try:
        key = PBKDF2(password, salt, dkLen=32, count=100000, hmac_hash_module=lambda: hashlib.sha256())
        print("✅ PBKDF2: Using lambda: hashlib.sha256()")
        return key
    except Exception:
        pass
    
    # Method 3: Try using Crypto.Hash.SHA256
    try:
        from Crypto.Hash import SHA256
        key = PBKDF2(password, salt, dkLen=32, count=100000, hmac_hash_module=SHA256)
        print("✅ PBKDF2: Using Crypto.Hash.SHA256")
        return key
    except Exception:
        pass
    
    # Method 4: Manual PBKDF2 implementation (fallback)
    print("🔄 PBKDF2: Using manual implementation")
    return pbkdf2_manual(password, salt, 100000, 32)


# ============================================================
#  🔥 MANUAL PBKDF2 IMPLEMENTATION (Fallback)
# ============================================================
def pbkdf2_manual(password: str, salt: bytes, iterations: int, dklen: int) -> bytes:
    """
    Manual PBKDF2 implementation using HMAC-SHA256.
    This is a fallback for when the Crypto library fails.
    """
    password_bytes = password.encode('utf-8') if isinstance(password, str) else password
    
    def prf(data: bytes) -> bytes:
        """HMAC-SHA256 pseudo-random function"""
        return hmac.new(password_bytes, data, hashlib.sha256).digest()
    
    # Calculate number of blocks needed
    blocks = (dklen + 31) // 32
    result = b''
    
    for i in range(1, blocks + 1):
        # U1 = PRF(password, salt || INT(i))
        u = prf(salt + i.to_bytes(4, 'big'))
        t = u
        
        # U2 = PRF(password, U1), U3 = PRF(password, U2), ...
        for _ in range(iterations - 1):
            u = prf(u)
            t = bytes(x ^ y for x, y in zip(t, u))
        
        result += t
    
    return result[:dklen]

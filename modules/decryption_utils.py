# modules/decryption_utils.py
import json
import base64
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Util.Padding import unpad
import hashlib
import re

async def decrypt_auth_string(encrypted_base64: str) -> dict:
    """
    Decrypts the AES-256-CBC encrypted auth string.
    Returns a dictionary containing 'token' and 'randomId'.
    """
    password = 'DDMM6767YYCC'
    
    try:
        # ============================================================
        #  🔥 FIX 1: Clean the Auth String
        # ============================================================
        # Remove all whitespace, newlines, and extra characters
        encrypted_base64 = re.sub(r'\s+', '', encrypted_base64)
        
        # URL-safe Base64 to Standard Base64
        encrypted_base64 = encrypted_base64.replace('-', '+').replace('_', '/')
        
        # ============================================================
        #  🔥 FIX 2: Add proper Base64 padding
        # ============================================================
        # Base64 length must be multiple of 4
        missing_padding = len(encrypted_base64) % 4
        if missing_padding:
            encrypted_base64 += '=' * (4 - missing_padding)
        
        print(f"🔑 Auth String (cleaned): {encrypted_base64[:50]}...")
        
        # ============================================================
        #  🔥 FIX 3: Decode Base64
        # ============================================================
        try:
            encrypted_data = base64.b64decode(encrypted_base64)
        except Exception as e:
            # Try with URL-safe decoding
            try:
                encrypted_data = base64.urlsafe_b64decode(encrypted_base64)
            except Exception as e2:
                raise ValueError(f"Base64 decode failed: {str(e2)}")
        
        print(f"📦 Decoded data length: {len(encrypted_data)} bytes")
        
        # ============================================================
        #  🔥 FIX 4: Extract Salt, IV, and Ciphertext
        # ============================================================
        if len(encrypted_data) < 48:  # 16 (salt) + 16 (iv) + 16 (min ciphertext)
            raise ValueError(f"Data too short: {len(encrypted_data)} bytes. Expected at least 48.")
        
        salt = encrypted_data[:16]
        iv = encrypted_data[16:32]
        ciphertext = encrypted_data[32:]
        
        print(f"🧂 Salt: {salt.hex()[:16]}...")
        print(f"🔑 IV: {iv.hex()[:16]}...")
        print(f"📄 Ciphertext length: {len(ciphertext)} bytes")
        
        # ============================================================
        #  🔥 FIX 5: Derive Key using PBKDF2
        # ============================================================
        try:
            key = PBKDF2(password, salt, dkLen=32, count=100000, hmac_hash_module=hashlib.sha256)
        except Exception as e:
            raise ValueError(f"PBKDF2 key derivation failed: {str(e)}")
        
        print(f"🔐 Key derived: {key.hex()[:16]}...")
        
        # ============================================================
        #  🔥 FIX 6: Decrypt
        # ============================================================
        try:
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted_padded = cipher.decrypt(ciphertext)
        except Exception as e:
            raise ValueError(f"AES decryption failed: {str(e)}")
        
        # ============================================================
        #  🔥 FIX 7: Unpad
        # ============================================================
        try:
            decrypted = unpad(decrypted_padded, AES.block_size)
        except ValueError as e:
            # Try removing padding manually
            try:
                pad_len = decrypted_padded[-1]
                if pad_len < AES.block_size:
                    decrypted = decrypted_padded[:-pad_len]
                else:
                    raise ValueError(f"Invalid padding: {e}")
            except Exception as e2:
                raise ValueError(f"Unpadding failed: {str(e)}. Original error: {str(e)}")
        
        print(f"✅ Decrypted data length: {len(decrypted)} bytes")
        
        # ============================================================
        #  🔥 FIX 8: Parse JSON
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
        #  🔥 FIX 9: Extract required fields
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
        # ============================================================
        #  🔥 FIX 10: Detailed error logging
        # ============================================================
        error_msg = str(e)
        print(f"❌ Decryption error: {error_msg}")
        print(f"❌ Auth String (first 100 chars): {encrypted_base64[:100]}...")
        raise ValueError(f"Decryption failed: {error_msg}")

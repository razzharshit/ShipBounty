"""Re-encrypt stored OAuth credentials with the primary configured Fernet key."""

from app.core.security import decrypt_oauth_token, encrypt_oauth_token
from app.db.session import SessionLocal
from app.models.authorization import OAuthCredential


def main() -> None:
    db = SessionLocal()
    rotated = 0
    try:
        for credential in db.query(OAuthCredential).yield_per(100):
            access_token = decrypt_oauth_token(
                credential.access_token_ciphertext, credential.encryption_key_id
            )
            access_ciphertext, primary_key_id = encrypt_oauth_token(access_token)
            credential.access_token_ciphertext = access_ciphertext
            if credential.refresh_token_ciphertext:
                refresh_token = decrypt_oauth_token(
                    credential.refresh_token_ciphertext,
                    credential.encryption_key_id,
                )
                refresh_ciphertext, refresh_key_id = encrypt_oauth_token(refresh_token)
                if refresh_key_id != primary_key_id:
                    raise RuntimeError("Primary key changed during rotation")
                credential.refresh_token_ciphertext = refresh_ciphertext
            credential.encryption_key_id = primary_key_id
            rotated += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"Rotated {rotated} OAuth credential(s).")


if __name__ == "__main__":
    main()

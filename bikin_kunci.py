import bcrypt

# Password yang mau lu pake buat login
password_asli = "admin123"

# Bikin hash rahasia (Bulletproof, stabil permanen)
hashed_password = bcrypt.hashpw(password_asli.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

print("KOPI KODE DI BAWAH INI KE config.yaml LU:")
print("-------------------------------------")
print(hashed_password)
print("-------------------------------------")
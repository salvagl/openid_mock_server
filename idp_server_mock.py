from flask import Flask, request, jsonify, redirect, session
import jwt
import datetime
import uuid
import json
import traceback

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Load settings
with open('settings.json') as f:
    settings = json.load(f)
    users = settings["users"]
    clients = settings["clients"]
    signing_keys = settings["signing_keys"]
    token_lifetime = settings.get("token_lifetime", 3600)

SECRET_KEY = "your_secret_key"

OIDC_CONFIG = {
    "issuer": "http://localhost:44366",
    "authorization_endpoint": "http://localhost:44366/authorize",
    "token_endpoint": "http://localhost:44366/token",
    "userinfo_endpoint": "http://localhost:44366/userinfo",
    "jwks_uri": "http://localhost:44366/.well-known/jwks",
    "response_types_supported": ["code", "token", "id_token"],
    "grant_types_supported": ["authorization_code", "implicit", "password", "client_credentials"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256", "HS256"]
}

def generate_token(username, client_id, signing_alg, signing_key):
    user = users.get(username)
    exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    payload = {
        "sub": user["sub"],
        "name": user["name"],
        "given_name": user["given_name"],
        "family_name": user["family_name"],
        "login": user["login"],
        "roles": user["roles"],
        "exp": exp,
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "client_id": client_id
    }

    if signing_alg == "RS256":
        # Aquí el signing_key será una clave pública RSA, necesitarás asegurarte de tenerla cargada.
        token = jwt.encode(payload, signing_key, algorithm="RS256")
    else:
        # Para HS256, se usa una clave secreta
        token = jwt.encode(payload, signing_key, algorithm="HS256")

    # Access token
    access_token = jwt.encode(payload, signing_key, algorithm=signing_alg)

    # ID Token (same payload but signed differently based on signing algorithm)
    id_token = jwt.encode(payload, signing_key, algorithm=signing_alg)

    return {
        "access_token": access_token,
        "id_token": id_token,
        "token_type": "Bearer",
        "expires_in": token_lifetime
    }


@app.route("/.well-known/openid-configuration", methods=["GET"])
def openid_config():
    return jsonify(OIDC_CONFIG)

@app.route("/authorize", methods=["GET"])
def authorize():
    client_id = request.args.get("client_id")
    redirect_uri = request.args.get("redirect_uri")
    response_type = request.args.get("response_type")
    state = request.args.get("state")
    
    client = next((c for c in clients if c["client_id"] == client_id), None)
    if not client:
        return jsonify({"error": "invalid_client"}), 400
    
    session["client_id"] = client_id
    session["redirect_uri"] = redirect_uri
    session["response_type"] = response_type
    session["state"] = state
    
    return "<form action='/login' method='post'><input name='username'><input type='password' name='password'><button type='submit'>Login</button></form>"

@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")
    
    if username not in users or users[username]["password"] != password:
        return jsonify({"error": "invalid_grant"}), 400
    
    session["username"] = username
    
    code = str(uuid.uuid4())
    session["code"] = code
    
    redirect_uri = session.get("redirect_uri")
    state = session.get("state", "")
    
    return redirect(f"{redirect_uri}?code={code}&state={state}")

@app.route("/token", methods=["POST"])
def token():
    grant_type = request.form.get("grant_type")
    client_id = request.form.get("client_id")
    client_secret = request.form.get("client_secret")
    code = request.form.get("code")
    username = request.form.get("username")
    password = request.form.get("password")

    client = next((c for c in clients if c["client_id"] == client_id and c["client_secret"] == client_secret), None)
    if not client:
        return jsonify({"error": "invalid_client"}), 400

    signing_alg = client["signing_alg"]
    signing_key = signing_keys.get(client["client_id"])
    
    if grant_type == "authorization_code":
        if code != session.get("code"):
            return jsonify({"error": "invalid_grant"}), 400
        return jsonify(generate_token(session["username"], client_id, signing_alg, signing_key))
    
    if grant_type == "password":
        if username not in users or users[username]["password"] != password:
            return jsonify({"error": "invalid_grant"}), 400
        return jsonify(generate_token(username, client_id, signing_alg, signing_key))
    
    if grant_type == "client_credentials":
        return jsonify(generate_token(client_id, client_id, signing_alg, signing_key))
    
    return jsonify({"error": "unsupported_grant_type"}), 400

@app.route("/.well-known/jwks", methods=["GET"])
def jwks():
    return jsonify(signing_keys)

@app.route("/userinfo", methods=["GET"])
def userinfo():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"error": "missing_authorization"}), 401
    
    token = auth_header.split()[1]
    try:
        # Extraer el header del token para ver con qué algoritmo fue firmado
        header = jwt.get_unverified_header(token)
        
        # Decodificar sin verificar para extraer el client_id
        payload = jwt.decode(token, options={"verify_signature": False})
        client_id = payload.get("client_id")

        # Obtener la clave correcta basada en el client_id
        signing_key = signing_keys.get(client_id)
        if not signing_key:
            print("Invalid Token Error: No signing key found for client_id", client_id)
            return jsonify({"error": "invalid_token"}), 401

        # Decodificar el token con la clave correcta
        payload = jwt.decode(token, signing_key, algorithms=[header["alg"]])

    except jwt.ExpiredSignatureError:
        print("Token Expired Error:", traceback.format_exc())
        return jsonify({"error": "token_expired"}), 401
    except jwt.InvalidTokenError:
        print("Invalid Token Error:", traceback.format_exc())
        return jsonify({"error": "invalid_token"}), 401
    
    #user = users.get(payload["sub"])
    user = next((u for u in users.values() if u["sub"] == payload["sub"]), None)
    if not user:
        print("User Not Found Error:", traceback.format_exc())
        return jsonify({"error": "user_not_found"}), 404
    
    return jsonify(user)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=44366)

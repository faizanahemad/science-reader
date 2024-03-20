from flask import Flask, redirect, url_for, session, flash
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer import oauth_authorized
import os

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersekrit")  # You should ideally use a more secure secret key!

google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    scope=["profile", "email"],
    redirect_url="/login/google/authorized"
)
app.register_blueprint(google_bp, url_prefix="/login")


@app.route("/")
def index():
    if not google.authorized:
        return redirect(url_for("google.login"))
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        return "Failed to fetch user information."
    email = resp.json()["email"]
    return f"Welcome, {email}!"


@app.route("/logout")
def logout():
    if google.authorized:
        token = google.token["access_token"]
        resp = google.session.post(
            "https://accounts.google.com/o/oauth2/revoke",
            params={"token": token},
            headers={"content-type": "application/x-www-form-urlencoded"}
        )

        # Delete OAuth token from the session if the revoke was successful
        if resp.ok:
            del google.token
            flash("You have been logged out.", category="success")
        else:
            flash("Logout failed.", category="error")

    return redirect(url_for("/"))


# Signal to handle login success redirection
@oauth_authorized.connect_via(google_bp)
def google_logged_in(blueprint, token):
    if not token:
        flash("Failed to log in with Google.", category="error")
        return False

    flash("Successfully logged in with Google.", category="success")
    return redirect(url_for("/"))


if __name__ == "__main__":
    app.run(ssl_context="adhoc", port=5000)

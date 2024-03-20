import os

from flask import Flask, request, redirect, url_for, session, flash
import csv

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Change this to a random secret key

def check_credentials(username, password):
    return os.getenv("PASSWORD", None) == password

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if check_credentials(username, password):
            session['username'] = username
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password')
    return '''
        <form method="post">
            Username: <input type="text" name="username"><br>
            Password: <input type="password" name="password"><br>
            <input type="submit" value="Login">
        </form>
    '''

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/')
def home():
    if 'username' not in session:
        return redirect(url_for('login'))
    return 'Welcome, {}! <a href="/logout">Logout</a>'.format(session['username'])

if __name__ == '__main__':
    app.run(ssl_context='adhoc')

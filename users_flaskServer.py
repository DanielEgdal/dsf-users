from flask import session, Flask, render_template,request,redirect,url_for,jsonify,Response,flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, or_,and_
import re
from functools import wraps
from datetime import datetime,timedelta
from map_medlemmer import make_map,get_postnummer_mapping
from read_extern import *
from markupsafe import escape
from WCIFManipMedlemmer import *
from last_competed import *
from models import *

from secret_key import secret_key,mysql_code

app = Flask(__name__)

app.config.update(
    SECRET_KEY = secret_key,
    SESSION_COOKIE_SECURE = True,
    PERMANENT_SESSION_LIFETIME = 7200,
    # SQLALCHEMY_DATABASE_URI = "sqlite:///medlemmer.sqlite3",
    SQLALCHEMY_DATABASE_URI = mysql_code,
    SQLAlCHEMY_TRACK_MODIFICATIONS = False
)

init_db(app)


with app.app_context():
    # from sqlalchemy import MetaData, Table, create_engine

    # engine = create_engine('sqlite:///medlemmer.sqlite3')

    # with engine.connect() as conn:
    #     conn.execute(text('ALTER TABLE extrenal_payments RENAME TO external_payments'))

    # db.session.execute(text("ALTER TABLE extrenal_payments RENAME COLUMN payment_time TO payment_date"))
    # db.session.execute(text("DROP TABLE extrenal_payments"))
    db.create_all()
    

def is_admin():
    curr = Users.query.filter_by(user_id = session['id']).first()
    if curr:
        if curr.user_id in set([admin.user_id for admin in Admins.query.all()]):
            return True
        else:
            return False
    else:
        return False
    
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_admin():
            return render_template("need_to_be_admin.html", user_name=session['name'])
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def give_name():
    if 'name' not in session:
        session['name'] = None
    if 'id' not in session:
        session['id'] = None

@app.route('/')
def startPage():
    if session['id']:
        return redirect(url_for("me"))
    return render_template('index.html',user_name=session['name'],admin=is_admin())

@app.route("/localhost")
def localhost_login():
    return redirect("https://www.worldcubeassociation.org/oauth/authorize?client_id=-BowqxQ4-RGEk8XdUGFb41AkWX_k1XSGiVJDDfm7k9M&redirect_uri=http%3A%2F%2Flocalhost%3A5000%2Fshow_token&response_type=token&scope=manage_competitions+public+email")

@app.route('/logout',methods=['GET','POST'])
def logout():
    keys = [key for key in session.keys()]
    for key in keys:
        session.pop(key)
    return redirect(url_for('startPage'))

@app.route('/show_token') 
def show_token():
    return render_template('show_token.html',user_name=session['name'])

@app.route('/process_token',methods=['POST'])
def process_token():
    access_token_temp = escape(request.form['access_token'])
    access_token= access_token_temp.split('access_token=')[1].split('&')[0]
    session['token'] = {'Authorization':f"Bearer {access_token}"}
    me = get_me(session['token'])
    if me.status_code == 200:
        cont = json.loads(me.content)
        user_name = cont['me']['name']
        user_id = int(cont['me']['id'])
        user_wcaid = cont['me']['wca_id']
        user_mail = cont['me']['email']
        medlem = Users.query.filter_by(user_id=user_id)
        person = medlem.first()
        if person:
            first_time_medlem = medlem.filter(Users.first_login==None).first()
            if first_time_medlem:
                first_time_medlem.email = user_mail
                first_time_medlem.first_login = datetime.now()
                db.session.commit()
            else: # Returner to the website
                if person.email != user_mail or person.wca_id != user_wcaid:
                    person.email = user_mail
                    person.wca_id = user_wcaid
                    db.session.commit()
        else: # This is someone who is not currently a member and hasn't been seen in the DB
            user = Users(
                user_id,
                user_name,
                user_wcaid,
                user_mail,
                medlem=False,
                postnummer=None,
                modtag_mails=False,
                sidste_comp=None,
                first_login=datetime.now()
            )
            db.session.add(user)
            db.session.commit()
        
        session['name'] = user_name
        session['id'] = user_id
    return "Du bliver omstillet til din konto."

@app.route('/me', methods = ['GET','POST'])
def me():
    if session['id']:
        medlem = Users.query.filter_by(user_id=session['id']).first()
        if request.method == 'POST':
            modtag_mails = True if request.form.getlist("modtag_mails") else False
            membership = True if request.form.getlist("medlem") else False
            postnummer = escape(request.form['postnummer'])
            if postnummer:
                regex = r'^[\d]{4}$'
                match = re.search(regex, postnummer)
                if match:
                    medlem.postnummer = int(postnummer)
                else:
                    return "Du skrev et ugyldigt postnummer"
            medlem.modtag_mails = modtag_mails
            medlem.medlem = membership
            db.session.commit()
            return redirect(url_for("me"))
        else:
            activity = active_member(medlem)
            admin = is_admin()
            return render_template('logged_in.html',user_name=session['name'],user=medlem,activity=activity,admin=admin)   
    else:
        return render_template("not_logged_in.html")

@app.route("/admin")
@admin_required
def admin_overview():
    return render_template('admin_overview.html',user_name=session['name'],admin=True)

@app.route("/admin/update_last_competed")
@admin_required
def update_last_competed():
    df = get_df()
    users = Users.query.all()
    for user in users:
        if user.wca_id:
            code, last_comp = get_last_competed(df,user.wca_id)
            if code == 200:
                user.sidste_comp = last_comp
    db.session.commit()
    return redirect(url_for('admin_users'))

@admin_required
@app.route("/admin/comps")
def mangler_postnummer_choose_comp():
    comps = get_comming_danish_comps()
    return render_template('upcoming_comps.html',comps=comps,user_name=session['name'],admin=True)

@admin_required
@app.route("/admin/ugyldige_postnumre")
def ugyldige_postnumre():
    postnumre = set(get_postnummer_mapping().postalcode)
    users_wo_valid = []
    for user in Users.query.all():
        if user.postnummer and user.postnummer not in postnumre:
            users_wo_valid.append(user)
    return render_template('ugyldige_postnumre.html',users=users_wo_valid,user_name=session['name'],admin=True)

@admin_required
@app.route("/admin/comps/manglende_postnummer/<compid>")
def mangler_postnummer(compid):
    """Find all the competitors (who are members) for a comp which have missing membership details"""
    competitors = set(get_competitors_wcif(compid))
    users = Users.query.filter(Users.user_id.in_(competitors), Users.postnummer.is_(None), Users.medlem.is_(True)).all()
    
    return render_template('comp_manglede_oplysninger.html',users=users,compid=compid,user_name=session['name'],admin=True)

@admin_required
@app.route("/admin/reconnectID/<int:personid>")
def recheck_wcaid(personid):
    medlem = Users.query.filter_by(user_id=personid).first()
    if not medlem:
        return "Personen blev ikke fundet i databasen."
    response, (idd,name,wcaid) = get_data_from_wcaid(medlem.user_id)
    if wcaid:
        medlem.wca_id = wcaid
    else:
        return "Operation failed. The person probably doesn't have WCA ID connected on wca"
    db.session.commit()
    return redirect(url_for("edit_user_admin",userid=personid))

# @app.route("/admin/import")
def import_users(): # Unused
    return None
    # db.session.query(Users).filter(Users.name == None).delete()
    # db.session.commit()
    counter = 0
    fil = pd.read_csv("members_extern.tsv",delimiter='\t')
    fil['Sidste comp'] = pd.to_datetime(fil['Sidste comp'])
    fil['Postnummer'] = fil['Postnummer'].astype('Int64')

    for row in fil.values:
        if not pd.isnull(row[1]):
            existing_user = Users.query.filter_by(wca_id=row[1]).first()
            if existing_user:
                continue
            else:
                status, (user_id, name, wcaid) = get_data_from_wcaid(row[1])
        else:
            status, (user_id, name, wcaid) = get_data_from_wcaid(row[5])
        if status != 200:
            continue
        if pd.isna(row[3]):
            postnummer=None
        else:
            postnummer = row[3]
        existing_user = Users.query.filter_by(user_id=user_id).first()
        if not existing_user:
            user = Users(
                        user_id,
                        name,
                        wcaid,
                        email=None,
                        medlem=True,
                        postnummer= postnummer,
                        modtag_mails=False,
                        sidste_comp=row[2].to_pydatetime(),
                        first_login=None
                        )
            db.session.add(user)
            counter +=1
            if counter %10 == 0:
                print(counter)
                db.session.commit()
    db.session.commit()
    return redirect(url_for('admin_users'))

def get_active_members():
    fourteen_months_ago = datetime.now() - timedelta(days=14*30)

    active_users_and_payments = Users.query.join(External_payments, Users.user_id == External_payments.user_id, isouter=True)\
                .filter(or_(Users.sidste_comp >= fourteen_months_ago, 
                            External_payments.payment_date >= fourteen_months_ago))
    
    users = active_users_and_payments.filter(Users.medlem==True).all()
    return users

@app.route('/admin/users')
@admin_required
def admin_users():
    # users = Users.query.all()
    users = get_active_members()
    return render_template('admin_users.html', users=users,antal=len(users),user_name=session['name'],admin=True)

@app.route('/admin/inaktive_users')
@admin_required
def inactive_users():
    all_users = Users.query.all()
    users = get_active_members()
    inactive_users = [user for user in all_users if user not in users]
    return render_template('inaktive_users.html', users=inactive_users,antal=len(inactive_users),user_name=session['name'],admin=True)

@app.route('/admin/users/<userid>',methods=['GET', 'POST'])
@admin_required
def edit_user_admin(userid):
    regex = r'^\d+$'
    match = re.search(regex, userid)
    if not match:
        return "Invalid user formatting. Must be an integer"
    medlem = Users.query.filter_by(user_id=userid).first()
    if not medlem:
        return "Invalid user id"
    if request.method == 'POST':
        modtag_mails = True if request.form.getlist("modtag_mails") else False
        membership = True if request.form.getlist("medlem") else False

        postnummer = escape(request.form['postnummer'])
        if postnummer:
            regex = r'^[\d]{4}$'
            match = re.search(regex, postnummer)
            if match:
                medlem.postnummer = int(postnummer)
            else:
                return "Du skrev et ugyldigt postnummer"
        medlem.modtag_mails = modtag_mails
        medlem.medlem = membership
        db.session.commit()
        return redirect(url_for("edit_user_admin",userid=userid))
    else:
        activity = active_member(medlem)
        return render_template('edit_account.html', user_name=session['name'],user=medlem,activity=activity,admin=True)

@app.route('/admin/new_user', methods=['GET', 'POST'])
@admin_required
def new_user():
    if request.method == 'POST':
        # userid = get_data_from_wcaid(request.form['wca_id'])
        wcaid = request.form['wca_id']
        user_id = request.form['user_id']
        postnummer= request.form['postnummer']
        if not wcaid:
            wcaid = None
            if user_id:
                status, (user_id, name, wcaid) =  get_data_from_wcaid(request.form['user_id'])
            else:
                return "Either the wcaid or userid must be filled out."
        else:
            status, (user_id, name, wcaid) =  get_data_from_wcaid(request.form['wca_id'])
        if not postnummer:
            postnummer = None
        existing = Users.query.filter_by(user_id = user_id).first()
        if existing:
            return f"Bruger-IDet {user_id} findes allerede i databasen. Du må gå ind i rette vedkommendes bruger i stedet."
        user = Users(
            userid = user_id,
            name=name,
            wcaid=wcaid,
            medlem=True,
            postnummer= postnummer,
            email=None,
            modtag_mails=False,
            sidste_comp=None,
            first_login=None,
        )
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('admin_users'))
    else:
        return render_template('new_user.html',user_name=session['name'],admin=True)

@app.route('/admin/admins', methods=['GET', 'POST'])
@admin_required
def modify_admin():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        
        user = Users.query.filter_by(user_id=user_id).first()
        if user:
            admin = Admins(
                user_id = user_id
            )
            db.session.add(admin)
            db.session.commit()
        return redirect(url_for('modify_admin'))
    else:
        admins = Admins.query.all()

        return render_template('admins.html', admins=admins,user_name=session['name'],admin=True)

@app.route('/admin/payments')
@admin_required
def display_payments():
    payments = External_payments.query.all()
    return render_template('payments.html', payments=payments,user_name=session['name'],admin=True)

@app.route('/admin/add_payment', methods=['GET', 'POST'])
@admin_required
def add_payment():
    if request.method == 'POST':
        user_id = request.form['user_id']
        payment_date = datetime.strptime(request.form['payment_date'], '%Y-%m-%dT%H:%M').date()
        # Add the payment to the Payments table
        payment = External_payments(user_id=user_id, payment_date=payment_date)
        db.session.add(payment)
        db.session.commit()
        return redirect(url_for('display_payments'))
    else:
        # Render a form for adding a payment
        return render_template('add_payment.html',user_name=session['name'],admin=True)

@app.route("/admin/user_map")
@admin_required
def make_admin_map():
    users = get_active_members()
    map_ = make_map(users)._repr_html_()
    return render_template("medlem_map.html",user_name=session['name'],map_=map_,admin=True)

# app.run(host=host,port=port)
# app.run(debug=True)

if __name__ == '__main__':
    app.run(port=5000,debug=True)


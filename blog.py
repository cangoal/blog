import os
import webapp2
import jinja2
import re
import hashlib
import hmac
import random
import logging
from xml.dom import minidom
from string import letters
from google.appengine.ext import db
from google.appengine.api import memcache


# ******************* configs & helper methods & base handler **************************

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir), autoescape = True)

# DEBUG = os.environ['SERVER_SOFEWARE'].startswith('Developmemt')
SECRET = "thisisasecret"
art_key = db.Key.from_path('ASCIIChan', 'arts')

def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)

def make_secure_val(val):
	return "%s|%s" % (val, hmac.new(SECRET, val).hexdigest())

def check_secure_val(sercure_val):
	val = sercure_val.split('|')[0]
	if sercure_val == make_secure_val(val):
		return val

def make_salt(length = 5):
    return ''.join(random.choice(letters) for x in xrange(length))

def make_pw_hash(name, pw, salt = None):
    if not salt:
        salt = make_salt()
    h = hashlib.sha256(name + pw + salt).hexdigest()
    return '%s,%s' % (salt, h)

def valid_pw(name, password, h):
	salt = h.split(',')[0]
	return h == make_pw_hash(name, password, salt)

def users_key(group = 'default'):
	return db.Key.from_path('users', group)

# defind user model
class User(db.Model):
	name = db.StringProperty(required = True)
	pw_hash = db.StringProperty(required = True)
	email = db.StringProperty()

	@classmethod
	def by_id(cls, uid):
		return User.get_by_id(uid, parent = users_key())

	@classmethod
	def by_name(cls, name):
		u = User.all().filter('name =', name).get()
		return u

	@classmethod
	def register(cls, name, pw, email = None):
		pw_hash = make_pw_hash(name, pw)
		return User(parent = users_key(),
					name = name,
					pw_hash = pw_hash,
					email = email)

	@classmethod
	def login(cls, name, pw):
		u = cls.by_name(name)
		if u and valid_pw(name, pw, u.pw_hash):
			return u

# base handler
class BaseHandler(webapp2.RequestHandler):
	def write(self, *a, **kw):
		self.response.out.write(*a, **kw)

	def render_str(self, template, **params):
		return render_str(template, **params)

	def render(self, template, **kw):
		self.write(self.render_str(template, **kw))

	def set_secure_cookie(self, name, val):
		cookie_val = make_secure_val(val)
		self.response.headers.add_header('Set-Cookie', '%s=%s; Path=/' % (name, cookie_val))

	def read_sercure_cookie(self, name):
		cookie_val = self.request.cookies.get(name)
		return cookie_val and check_secure_val(cookie_val)

	def login(self, user):
		self.set_secure_cookie('user_id', str(user.key().id))

	def logout(self):
		self.response.headers.add_header('Set-Cookie', 'user_id=; Path=/')

	def initialize(self, *a, **kw):
		webapp2.RequestHandler.initialize(self, *a, **kw)
		uid = self.read_sercure_cookie('user_id')
		self.user = uid and User.by_id(int(uid))


# ******************* security and cookies stuff **************************

class MainPage(BaseHandler):
	def get(self):
		self.response.headers['Content-Type'] = 'text/plain'
		visits = 0
		visits_cookie_str = self.request.cookies.get('visits')
		if visits_cookie_str:
			cookie_val = check_secure_val(visits_cookie_str)
			if cookie_val:
				visits = int(cookie_val)
		visits += 1
		new_cookie_val = make_secure_val(str(visits))
		self.response.headers.add_header('Set-Cookie', 'visits=%s' % new_cookie_val)

		if visits > 10000:
			self.write("You are the best ever!")
		else:
			self.write("You've been here %d times!" % visits)




# ******************* ASCIIChan stuff **************************

# art modle
class Art(db.Model):
	title = db.StringProperty(required = True)
	art = db.TextProperty(required = True)
	created = db.DateTimeProperty(auto_now_add = True)
	coords = db.GeoPtProperty()

# retrieve top 10 ASCII arts
def top_arts(update = False):
	key = 'top'
	arts = memcache.get(key)
	if arts is None or update:
		logging.error("DB QUERY")
		arts = db.GqlQuery( "SELECT * "
							"FROM Art "
							"WHERE ANCESTOR IS :1 "
							"ORDER BY created DESC "
							"LIMIT 10", art_key)
		# prevent the running of multiple queries
		arts = list(arts)
		memcache.set(key, arts)
	return arts


# art page
class ArtPage(BaseHandler):
	def render_front(self, title="", art="", error=""):
		arts = top_arts()

		points = filter(None, (a.coords for a in arts))
		
		img_url = None
		if points:
			img_url = gmaps_img(points)

		self.render("front.html", title=title, art=art, error=error, arts=arts, img_url = img_url)

	def get(self):
		self.render_front()

	def post(self):
		title = self.request.get("title")
		art = self.request.get("art")

		if title and art:
			a = Art(parent = art_key, title = title, art = art)
			coords = get_coords(self.request.remote_addr)
			if coords:
				a.coords = coords
			a.put()
			# CACHE.clear()  #CACHE['top'] = None
			top_arts(True)
			self.redirect("/art")
		else:
			error = "we need both a title and some artwork!"
			self.render_front(title, art, error)

# retrive users' geo locations based on ip info
GMAPS_URL = "http://maps.googleapis.com/maps/api/staticmap?size=380x263&sensor=false&"
def gmaps_img(points):
	makers ='&'.join("markers=%s,%s" % (p.lat, p.lon) for p in points)
	return GMAPS_URL + makers

# looks like this api does not working
IP_URL = "http://api.hostip.info/?ip="
def get_coords(ip):
	ip='23.24.209.141'
	url = IP_URL + ip
	content = None
	try:
		content = rullib2.urlopen(url).read()
	except:
		# return
		logging.debug("Fail to get GeoPt!")
	if content:
		d = minidom.parseString(content)
		coords = d.getElmenetsByTagName("gml:coordinates")
		if coords and coords[0].childNodes[0].nodeValue:
			lon, lat = coords[0].childNodes[0].nodeValue.split(',')
			return db.GeoPt(lat, lon)
			# hard copied some values cause hostip api is not working
	return db.GeoPt('29.6516', '-82.3248')

# ******************* rot13 stuff **************************

# rot13 handler
class Rot13(BaseHandler):
	def get(self):
		self.render('rot13-form.html')

	def post(self):
		rot13=''
		text = self.request.get('text')
		if text:
			rot13 = text.encode('rot13')
		self.render('rot13-form.html', text = rot13)
	

# ******************* unit2 base sign up form stuff **************************

# sign up base hanlder, blog sign up handler and unit 2 sign up handler inherite from this handler
class Signup(BaseHandler):
	def get(self):
		self.render('signup-form.html')

	def post(self):
		have_error = False
		self.username = self.request.get('username')
		self.password = self.request.get('password')
		self.verify = self.request.get('verify')
		self.email = self.request.get('email')

		params = dict(username = self.username,
					  email = self.email)
		if not valid_username(self.username):
			params['error_username'] = "That's not a valid username."
			have_error = True
		if not valid_password(self.password):
			params['error_password'] = "That's not a valid password."
			have_error = True
		elif self.password != self.verify:
			params['error_verify'] = "Your passwords didn't match."
			have_error = True
		if not valid_email(self.email):
			params['error_email'] = "That's not a valid email."
			have_error = True

		if have_error:
			self.render('signup-form.html', **params)
		else:
			self.done()

	def done(self, *a, **kw):
		raise NotImplementedError

# unit2 sign up handler
class Unit2Signup(Signup):
	def done(self):
		self.redirect('/welcome?username=' + username)

# regex validation for sign up form page
USER_RE = re.compile(r"^[a-zA-Z0-9_-]{3,20}$")
def valid_username(username):
	return username and USER_RE.match(username)

PASS_RE = re.compile(r"^.{3,20}$")
def valid_password(password):
	return password and PASS_RE.match(password)

EMAIL_RE = re.compile(r"^[\S]+@[\S]+\.[\S]+$")
def valid_email(email):
	return not email or EMAIL_RE.match(email)


# welcome page
class Welcome(BaseHandler):
	def get(self):
		if self.user:
			self.render('welcome.html', username = self.user.name)
		else:
			self.redirect('/signup')


# ******************* blog stuff **************************

def blog_key(name = 'default'):
	return db.Key.from_path('blogs', name)

# Post model defined
class Post(db.Model):
	subject = db.StringProperty(required = True)
	content = db.TextProperty(required = True)
	created = db.DateTimeProperty(auto_now_add = True)
	last_modified = db.DateTimeProperty(auto_now = True)

	def render(self):
		self._render_text = self.content.replace('\n', '<br>')
		return render_str("post.html", p = self)


# blog main page
class BlogFront(BaseHandler):
	def get(self):
		# GqlQuery 
		posts = db.GqlQuery("select * from Post order by created desc limit 10")
		# posts = Post.all().order('-created')
		self.render('blog-front.html', posts = posts)


# view post detail
class PostPage(BaseHandler):
	def get(self, post_id):
		key = db.Key.from_path('Post', int(post_id), parent=blog_key())
		post = db.get(key)

		if not post:
			self.error(404)
			return
		self.render("permalink.html", post = post)


# create new post
class NewPost(BaseHandler):
	def get(self):
		self.render("newpost.html")

	def post(self):
		subject = self.request.get('subject')
		content = self.request.get('content')

		if subject and content:
			p = Post(parent = blog_key(), subject = subject, content = content)
			p.put();
			self.redirect('/blog/%s' % str(p.key().id()))
		else:
			error = "subject and content, please!"
			self.render("newpost.html", subject=subject, content=content, error=error)


# user sign up 
class Register(Signup):
	def done(self):
		u = User.by_name(self.username)
		if u:
			msg = 'That user already exists.'
			self.render('signup-form.html', error_username = msg)
		else:
			u = User.register(self.username, self.password, self.email)
			u.put()

			self.login(u)
			self.redirect('/blog')

# user log in 
class Login(BaseHandler):
	def get(self):
		self.render('login-form.html')

	def post(self):
		username = self.request.get('username')
		password = self.request.get('password')

		u = User.login(username, password)
		if u:
			 self.login(u)
			 self.redirect('/blog')
		else:
			msg = 'Invalid login'
			self.render('login-form.html', error = msg)


# user log out
class Logout(BaseHandler):
	def get(self):
		self.logout()
		self.redirect('/signup')


# route config
app = webapp2.WSGIApplication([('/', MainPage),
							   ('/art', ArtPage),
							   ('/rot13', Rot13),
							   ('/unit2/signup', Unit2Signup),
							   ('/welcome', Welcome),
							   ('/blog/?', BlogFront),
							   ('/blog/([0-9]+)', PostPage),
							   ('/blog/newpost', NewPost),
							   ('/signup', Register),
							   ('/login', Login),
							   ('/logout', Logout)
							   ], debug=True)
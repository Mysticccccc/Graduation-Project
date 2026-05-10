try:
    import pymysql
except ImportError:
    pymysql = None
else:
    pymysql.install_as_MySQLdb()

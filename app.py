from flask import Flask, request

app=Flask(__name__)


@app.route('/')
def main():
    return('hola mundo')

@app.route('/params/')
@app.route('/params/<name>/')
@app.route('/params/<name>/<lasname>')
@app.route('/params/<name>/<lasname>/<int:num>')
def aparams(name='sin valor', lasname='sin apellido', num='sincedula'):
    param = request.args.get('params1','no contiene este argumento')
    return 'el parametroes : {} {} {}'.format(name, lasname, num)

if __name__ == '__main__':
    app.run(debug=True)
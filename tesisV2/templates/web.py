from flask import Flask, render_template, request, redirect
import toml
import os

app = Flask(__name__)
CONFIG_FILE = "/home/liade/tesis/config.toml"

@app.route('/', methods=['GET', 'POST'])
def index():
    # 1. Leer el archivo de configuración actual
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = toml.load(f)
    except Exception as e:
        return f"Error crítico leyendo el archivo config.toml: {e}", 500

    # 2. Si el usuario modifica parámetros desde la web y presiona Guardar
    if request.method == 'POST':
        try:
            # --- GUARDAR DATOS MACETA 1 ---
            config['macetas']['maceta1']['umbral_humedad_suelo_raw'] = int(request.form['m1_suelo'])
            config['macetas']['maceta1']['umbral_humedad_ambiente_pct'] = float(request.form['m1_amb'])
            config['macetas']['maceta1']['tiempo_riego_seg'] = float(request.form['m1_riego'])
            config['macetas']['maceta1']['dli_objetivo'] = float(request.form['m1_dli'])

            # --- GUARDAR DATOS MACETA 2 ---
            config['macetas']['maceta2']['umbral_humedad_suelo_raw'] = int(request.form['m2_suelo'])
            config['macetas']['maceta2']['umbral_humedad_ambiente_pct'] = float(request.form['m2_amb'])
            config['macetas']['maceta2']['tiempo_riego_seg'] = float(request.form['m2_riego'])
            config['macetas']['maceta2']['dli_objetivo'] = float(request.form['m2_dli'])

            # Guardar físicamente los cambios sobrescribiendo el TOML
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                toml.dump(config, f)
            
            # Recargar la interfaz mostrando el cartel de éxito
            return redirect('/?success=1')
        
        except ValueError:
            return "Error: Uno de los valores ingresados no es un número válido.", 400

    # 3. Renderizar la página web inyectando los datos actuales del TOML
    success = request.args.get('success')
    return render_template('index.html', config=config, success=success)

if __name__ == '__main__':
    # Corre en el puerto 5000 de la interfaz local
    app.run(host='0.0.0.0', port=5000, debug=False)

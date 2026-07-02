from datetime import datetime
from typing import Optional, Tuple, List, Dict

from models import MacetaConfig, MacetaEstado, GlobalConfig


def esta_en_horario_activo(hora_actual: int, hora_inicio: int, hora_fin: int) -> bool:
    if hora_inicio < hora_fin:
        return hora_inicio <= hora_actual < hora_fin
    return hora_actual >= hora_inicio or hora_actual < hora_fin


def raw_a_porcentaje(raw_8bit: int, raw_seco: int, raw_mojado: int) -> int:
    humedad = int((raw_8bit - raw_seco) * 100 / (raw_mojado - raw_seco))
    return max(0, min(100, humedad))


def lectura_humedad_valida(raw_8bit: Optional[int]) -> bool:
    if raw_8bit is None:
        return False
    return 0 <= raw_8bit <= 255


def procesar_humedad_suelo(
    raw1: Optional[int],
    raw2: Optional[int],
    global_config: GlobalConfig
) -> Tuple[Optional[int], Optional[int], Optional[int], List[str]]:
    alertas = []

    val1 = lectura_humedad_valida(raw1)
    val2 = lectura_humedad_valida(raw2)

    hum1 = raw_a_porcentaje(raw1, global_config.raw_seco, global_config.raw_mojado) if val1 else None
    hum2 = raw_a_porcentaje(raw2, global_config.raw_seco, global_config.raw_mojado) if val2 else None

    if val1 and val2:
        promedio = int((hum1 + hum2) / 2)

        if abs(hum1 - hum2) > global_config.discrepancia_humedad_pct:
            alertas.append(f"Discrepancia alta entre sensores de humedad: {hum1}% vs {hum2}%")

        return hum1, hum2, promedio, alertas

    if val1 and not val2:
        alertas.append("Fallo sensor de humedad 2, se usa sensor 1")
        return hum1, None, hum1, alertas

    if val2 and not val1:
        alertas.append("Fallo sensor de humedad 1, se usa sensor 2")
        return None, hum2, hum2, alertas

    alertas.append("Fallo en ambos sensores de humedad de suelo")
    return None, None, None, alertas


def lectura_dht_valida(
    temperatura_c: Optional[float],
    humedad_ambiente_pct: Optional[float]
) -> bool:
    if temperatura_c is None or humedad_ambiente_pct is None:
        return False

    if not (-20 <= temperatura_c <= 80):
        return False

    if not (0 <= humedad_ambiente_pct <= 100):
        return False

    return True


def calcular_y_controlar_dli(
    maceta: MacetaConfig,
    lux_ambiente: Optional[float],
    dli_acumulado: float,
    luz_esta_encendida: bool,
    dt_segundos: float,
    ahora: datetime
) -> Tuple[bool, float, List[str]]:
    alertas = []

    # Chequeamos que este habilitada la luz antes de cualquier cosa
    if not maceta.luz.enabled:
        return False, dli_acumulado, alertas

    # Extraemos la configuracion diurna de la maceta
    hora_inicio = maceta.hora_inicio_dia
    hora_fin = maceta.hora_fin_dia
    dli_objetivo = maceta.dli_objetivo
    lux_foco = maceta.lux_foco
    F_L = maceta.factor_luminaria
    F_L_ambiente = maceta.factor_luminaria_ambiente

    # Calculo dinamico de PPFD y suma
    ppfd_foco = lux_foco * F_L
    ppfd_ambiente = (lux_ambiente * F_L_ambiente) if lux_ambiente is not None else 0.0
    ppfd_total = ppfd_ambiente + (ppfd_foco if luz_esta_encendida else 0.0)

    # Integramos
    horas_transcurridas = dt_segundos / 3600.0
    incremento_dli = 0.0036 * ppfd_total * horas_transcurridas
    nuevo_dli = dli_acumulado + incremento_dli

    # --- EVALUACION DEL FOTOPERIODO ---
    hora_actual_decimal = ahora.hour + (ahora.minute / 60.0)

    # Verificamos si estamos dentro del horario
    if hora_inicio <= hora_actual_decimal < hora_fin:
        en_horario = True
    else:
        en_horario = False

    if not en_horario:
        return False, nuevo_dli, alertas

    # Calculamos Ti restante y evaluamos cuanto le falta
    Ti_restante = hora_fin - hora_actual_decimal
    dli_faltante = dli_objetivo - nuevo_dli

    if dli_faltante <= 0:
        return False, nuevo_dli, alertas  # Ya se cumplio la meta de hoy

    dli_potencial_foco = 0.0036 * ppfd_foco * Ti_restante

    # Decision final de encendido
    encender_foco = dli_potencial_foco <= dli_faltante

    return encender_foco, nuevo_dli, alertas


def decidir_ventilacion(
    maceta: MacetaConfig,
    estado: MacetaEstado,
    temperatura_c: Optional[float],
    humedad_ambiente_pct: Optional[float],
    dt_segundos: float
) -> Tuple[bool, List[str]]:
    alertas = []

    if not maceta.ventilador.enabled:
        return False, alertas

    # --- 1. GESTION DEL TEMPORIZADOR (Histeresis) ---
    # Si el ventilador ya esta encendido, le restamos el tiempo que paso
    if estado.tiempo_ventilacion_restante_seg > 0:
        estado.tiempo_ventilacion_restante_seg -= dt_segundos

        if estado.tiempo_ventilacion_restante_seg > 0:
            return True, alertas  # Mientras ventila, retorna True directo y no acumula historial
        else:
            estado.tiempo_ventilacion_restante_seg = 0.0  # El tiempo termino

    # --- 2. FILTRADO Y MEMORIA ---
    if not lectura_dht_valida(temperatura_c, humedad_ambiente_pct):
        alertas.append("Lectura invalida de DHT, se omite logica de ventilacion")
        return False, alertas

    # Guardamos la lectura actual en la memoria
    estado.historial_humedad_ambiente.append(humedad_ambiente_pct)

    # Mantenemos solo las ultimas 5 mediciones
    if len(estado.historial_humedad_ambiente) > 5:
        estado.historial_humedad_ambiente.pop(0)

    # --- 3. DECISION DE ENCENDIDO ---
    tiempo_encendido = 120.0  # Bloque minimo de ventilacion en segundos (2 minutos)

    # Condicion A: Exceso de temperatura (Reaccion inmediata)
    if temperatura_c > maceta.umbral_temperatura_c:
        alertas.append(f"Temperatura alta ({temperatura_c:.1f} C). Ventilador activado.")
        estado.tiempo_ventilacion_restante_seg = tiempo_encendido
        estado.historial_humedad_ambiente.clear()  # Vaciamos por seguridad
        return True, alertas

    # Condicion B: Exceso de Humedad (Promedio de 5 mediciones)
    if len(estado.historial_humedad_ambiente) == 5:
        promedio_humedad = sum(estado.historial_humedad_ambiente) / 5.0

        if promedio_humedad > maceta.umbral_humedad_ambiente_pct:
            alertas.append(f"Humedad alta prolongada (Promedio: {promedio_humedad:.1f}%). Ventilador activado.")
            estado.tiempo_ventilacion_restante_seg = tiempo_encendido

            # --- BARRIDO DE MEMORIA AMBIENTAL ---
            # Borramos el historial para que empiece a recolectar de cero al apagarse
            estado.historial_humedad_ambiente.clear()
            return True, alertas

    return False, alertas


def decidir_riego(maceta: MacetaConfig, raw_promedio_suavizado: Optional[float]) -> Tuple[bool, List[str]]:
    alertas = []

    if raw_promedio_suavizado is None:
        return False, alertas

    # Logica de riego en RAW (mayor o igual al umbral)
    riego = raw_promedio_suavizado >= maceta.umbral_humedad_suelo_raw

    if riego:
        alertas.append(f"Tierra seca (Raw: {raw_promedio_suavizado:.1f} >= {maceta.umbral_humedad_suelo_raw}). Riego activado.")

    return riego, alertas


def procesar_maceta(
    maceta: MacetaConfig,
    estado: MacetaEstado,
    lecturas: Dict[str, Optional[float]],
    global_config: GlobalConfig,
    dli_acumulado_actual: float = 0.0,
    dt_segundos: float = 0.0,
    ahora: Optional[datetime] = None
) -> Tuple[MacetaEstado, float]:
    if ahora is None:
        ahora = datetime.now()

    nuevo_estado = MacetaEstado()

    # --- 1. RECUPERAR MEMORIA Y FILTRAR ERRORES ---
    nuevo_estado.historial_raw_1 = estado.historial_raw_1.copy()
    nuevo_estado.historial_raw_2 = estado.historial_raw_2.copy()

    # --- MEMORIA PARA EL VENTILADOR TRASLADADA ---
    nuevo_estado.historial_humedad_ambiente = estado.historial_humedad_ambiente.copy()
    nuevo_estado.tiempo_ventilacion_restante_seg = estado.tiempo_ventilacion_restante_seg

    raw1_actual = lecturas.get("humedad_raw_1")
    raw2_actual = lecturas.get("humedad_raw_2")

    # Guardamos solo si es valido y DISTINTO de 128
    if raw1_actual is not None and raw1_actual != 128:
        nuevo_estado.historial_raw_1.append(raw1_actual)
        if len(nuevo_estado.historial_raw_1) > 3:
            nuevo_estado.historial_raw_1.pop(0)

    if raw2_actual is not None and raw2_actual != 128:
        nuevo_estado.historial_raw_2.append(raw2_actual)
        if len(nuevo_estado.historial_raw_2) > 3:
            nuevo_estado.historial_raw_2.pop(0)

    # --- CALCULO DE VALORES SUAVIZADOS ---
    # Obtenemos 3 lecturas para sacar el promedio y tomar decisiones.

    raw1_suavizado = sum(nuevo_estado.historial_raw_1) / 3 if len(nuevo_estado.historial_raw_1) == 3 else None
    raw2_suavizado = sum(nuevo_estado.historial_raw_2) / 3 if len(nuevo_estado.historial_raw_2) == 3 else None

    # Promedio unificado de la maceta para decidir el riego
    raws_validos = [r for r in (raw1_suavizado, raw2_suavizado) if r is not None]
    raw_promedio_suavizado = sum(raws_validos) / len(raws_validos) if raws_validos else None

    # --- NUEVO BLOQUE DE INTERCEPCION COHERENTE ---
    if raw1_suavizado is None and raw2_suavizado is None:
        # Si no hay 3 lecturas en memoria, no calculamos el porcentaje para evitar el error
        hum1, hum2, promedio_pct = None, None, None
        alertas_humedad = ["Recolectando muestras del sensor. Esperando 3 lecturas..."]
    else:
        # Si la memoria esta llena, procesamos normalmente y convertimos a porcentaje
        hum1, hum2, promedio_pct, alertas_humedad = procesar_humedad_suelo(
            raw1_suavizado, raw2_suavizado, global_config
        )

    # Guardamos el estado para el programa
    nuevo_estado.humedad_suelo_raw_1 = raw1_actual  # Guardamos el real para ver si saltan los 128
    nuevo_estado.humedad_suelo_raw_2 = raw2_actual
    nuevo_estado.humedad_suelo_1_pct = hum1
    nuevo_estado.humedad_suelo_2_pct = hum2
    nuevo_estado.humedad_suelo_promedio_pct = promedio_pct

    # --- 3. PROCESAR RESTO DE SENSORES ---
    lux = lecturas.get("lux")
    temperatura_c = lecturas.get("temperatura_c")
    humedad_ambiente_pct = lecturas.get("humedad_ambiente_pct")
    nuevo_estado.lux = lux

    if lectura_dht_valida(temperatura_c, humedad_ambiente_pct):
        nuevo_estado.temperatura_c = temperatura_c
        nuevo_estado.humedad_ambiente_pct = humedad_ambiente_pct
    else:
        nuevo_estado.temperatura_c = None
        nuevo_estado.humedad_ambiente_pct = None
        if maceta.dht.enabled:
            alertas_humedad.append("Lectura invalida de DHT")

    # --- 4. CONTROL DE LUZ (DLI) Y CLIMA ---
    luz_encendida, nuevo_dli, alertas_luz = calcular_y_controlar_dli(
        maceta=maceta,
        lux_ambiente=lux,
        dli_acumulado=dli_acumulado_actual,
        luz_esta_encendida=estado.luz_encendida,
        dt_segundos=dt_segundos,
        ahora=ahora
    )
    nuevo_estado.dli_acumulado = nuevo_dli

    ventilador_encendido, alertas_vent = decidir_ventilacion(
        maceta=maceta,
        estado=nuevo_estado,
        temperatura_c=nuevo_estado.temperatura_c,
        humedad_ambiente_pct=nuevo_estado.humedad_ambiente_pct,
        dt_segundos=dt_segundos
    )

    # --- 5. GATILLO DE RIEGO (Usando el Raw Suavizado) ---
    riego_pendiente, alertas_riego = decidir_riego(
        maceta,
        raw_promedio_suavizado
    )

    nuevo_estado.luz_encendida = luz_encendida
    nuevo_estado.ventilador_encendido = ventilador_encendido
    nuevo_estado.riego_pendiente = riego_pendiente
    nuevo_estado.alertas = alertas_humedad + alertas_luz + alertas_vent + alertas_riego

    return nuevo_estado, nuevo_dli

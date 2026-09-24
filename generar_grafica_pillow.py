"""
Reemplazo de generar_grafica() usando Pillow en vez de matplotlib.

Por qué: matplotlib trae extensiones nativas (_image.pyd) que en algunas
máquinas con políticas de Control de Aplicaciones de Windows (Smart App
Control / EDR corporativo) se bloquean al cargar. Pillow, al ya venir
como dependencia de ultralytics/torchvision, normalmente no dispara ese
bloqueo, así que dibujamos la gráfica de barras "a mano" con
ImageDraw sin depender de matplotlib para nada.
"""

from PIL import Image, ImageDraw, ImageFont


def generar_grafica(conteos, output_path):

    camaras = list(conteos.keys())
    cumple = [conteos[c]["cumple"] for c in camaras]
    incumplimiento = [conteos[c]["incumplimiento"] for c in camaras]

    # ------------------------------------------------------------
    # Configuración del lienzo
    # ------------------------------------------------------------

    ancho_img = 700
    alto_img = 450
    margen_izq = 60
    margen_inf = 80
    margen_sup = 60
    margen_der = 30

    area_ancho = ancho_img - margen_izq - margen_der
    area_alto = alto_img - margen_sup - margen_inf

    color_cumple = (46, 125, 50)          # verde
    color_incumplimiento = (198, 40, 40)  # rojo
    color_texto = (30, 30, 30)
    color_eje = (120, 120, 120)

    img = Image.new("RGB", (ancho_img, alto_img), "white")
    draw = ImageDraw.Draw(img)

    try:
        fuente_titulo = ImageFont.truetype("arial.ttf", 18)
        fuente_normal = ImageFont.truetype("arial.ttf", 13)
        fuente_valor = ImageFont.truetype("arial.ttf", 12)
    except OSError:
        # Si no encuentra Arial (Linux/mac o falta la fuente), usa la default
        fuente_titulo = ImageFont.load_default()
        fuente_normal = ImageFont.load_default()
        fuente_valor = ImageFont.load_default()

    # ------------------------------------------------------------
    # Título
    # ------------------------------------------------------------

    titulo = "Resumen semanal de EPP (DATOS DE PRUEBA)"
    draw.text((margen_izq, 15), titulo, fill=color_texto, font=fuente_titulo)

    # ------------------------------------------------------------
    # Escala vertical
    # ------------------------------------------------------------

    valor_max = max(cumple + incumplimiento) if (cumple + incumplimiento) else 1
    valor_max = max(valor_max, 1)

    def y_desde_valor(valor):
        return margen_sup + area_alto - (valor / valor_max) * area_alto

    # Eje Y (línea base)
    y_base = margen_sup + area_alto
    draw.line(
        [(margen_izq, y_base), (margen_izq + area_ancho, y_base)],
        fill=color_eje,
        width=2,
    )

    # ------------------------------------------------------------
    # Barras por cámara
    # ------------------------------------------------------------

    n_camaras = len(camaras)
    ancho_grupo = area_ancho / n_camaras if n_camaras else area_ancho
    ancho_barra = ancho_grupo * 0.3
    espacio_entre_barras = ancho_grupo * 0.05

    for i, camara in enumerate(camaras):

        centro_grupo = margen_izq + ancho_grupo * i + ancho_grupo / 2

        x_cumple = centro_grupo - espacio_entre_barras / 2 - ancho_barra
        x_incumplimiento = centro_grupo + espacio_entre_barras / 2

        valor_cumple = cumple[i]
        valor_incumplimiento = incumplimiento[i]

        y_cumple = y_desde_valor(valor_cumple)
        y_incumplimiento = y_desde_valor(valor_incumplimiento)

        # Barra "cumple"
        draw.rectangle(
            [x_cumple, y_cumple, x_cumple + ancho_barra, y_base],
            fill=color_cumple,
        )
        draw.text(
            (x_cumple + ancho_barra / 2, y_cumple - 18),
            str(valor_cumple),
            fill=color_texto,
            font=fuente_valor,
            anchor="mm",
        )

        # Barra "incumplimiento"
        draw.rectangle(
            [x_incumplimiento, y_incumplimiento, x_incumplimiento + ancho_barra, y_base],
            fill=color_incumplimiento,
        )
        draw.text(
            (x_incumplimiento + ancho_barra / 2, y_incumplimiento - 18),
            str(valor_incumplimiento),
            fill=color_texto,
            font=fuente_valor,
            anchor="mm",
        )

        # Etiqueta de la cámara
        draw.text(
            (centro_grupo, y_base + 15),
            camara,
            fill=color_texto,
            font=fuente_normal,
            anchor="mm",
        )

    # ------------------------------------------------------------
    # Leyenda
    # ------------------------------------------------------------

    leyenda_y = alto_img - 25

    draw.rectangle([margen_izq, leyenda_y, margen_izq + 15, leyenda_y + 15], fill=color_cumple)
    draw.text((margen_izq + 22, leyenda_y + 7), "Cumplimientos", fill=color_texto, font=fuente_normal, anchor="lm")

    leyenda_x2 = margen_izq + 180
    draw.rectangle([leyenda_x2, leyenda_y, leyenda_x2 + 15, leyenda_y + 15], fill=color_incumplimiento)
    draw.text((leyenda_x2 + 22, leyenda_y + 7), "Incumplimientos", fill=color_texto, font=fuente_normal, anchor="lm")

    # ------------------------------------------------------------
    # Guardar
    # ------------------------------------------------------------

    img.save(output_path, dpi=(150, 150))

    print(f"Gráfica de prueba guardada en {output_path}")
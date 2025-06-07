import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import subprocess
import threading
import os
import datetime
import shutil
import re # Módulo para expresiones regulares


# --- Configuración de rutas predeterminadas y variables globales ---
# No necesitamos una carpeta de destino predeterminada en Windows ahora,
# ya que los resultados van al directorio de origen de los FASTQ.

# Variables globales para las rutas que el usuario seleccionará en la GUI
RUTA_FASTQ_LECTURA1 = "" # Ruta del primer archivo FASTQ seleccionado en Windows
RUTA_FASTQ_LECTURA2 = "" # Ruta del segundo archivo FASTQ seleccionado en Windows

# Variable para el nombre del análisis ingresado por el usuario
NOMBRE_ANALISIS = ""

# Usuario actual de WSL (se obtendrá dinámicamente)
USUARIO_WSL_ACTUAL = None

# Ruta base donde se crearán los directorios de trabajo en WSL
RUTA_BASE_ANALISIS_WSL = None

# Ruta del genoma de referencia en WSL
RUTA_GENOMA_REFERENCIA_WSL = None

# Rutas completas de los archivos dentro del directorio de trabajo de WSL
RUTA_WSL_DIR_TRABAJO_ACTUAL = ""
RUTA_WSL_FASTQ_LECTURA1 = ""
RUTA_WSL_FASTQ_LECTURA2 = ""
RUTA_WSL_ARCHIVO_VCF_PIPELINE = "" # Ruta del VCF generado en WSL
RUTA_WSL_ARCHIVO_BAM_PIPELINE = "" # Ruta del BAM generado en WSL


# --- Variables globales para los widgets de Tkinter (para acceso desde hilos) ---
ventana = None
boton_ejecutar_wsl = None
output_text = None
label_fastq1_seleccionado = None
label_fastq2_seleccionado = None
entrada_nombre_analisis = None
label_estado_progreso = None # Nueva etiqueta para mostrar el estado actual
progress_bar = None # Barra de progreso
widgets_indicadores_pasos = [] # Para almacenar los labels de estado de cada paso


# --- Funciones ---

def convertir_ruta_windows_a_wsl(ruta_windows):
    if not ruta_windows:
        return ""
    # Convert backslashes to forward slashes
    ruta_convertida = ruta_windows.replace("\\", "/")
    # Match drive letter pattern e.g., C:/ D:/ etc.
    match = re.match(r"([a-zA-Z]):/", ruta_convertida)
    if match:
        letra_unidad = match.group(1).lower()
        # Replace C:/ with /mnt/c/
        ruta_sin_unidad = ruta_convertida[len(match.group(0)):] # Get the rest of the path
        ruta_wsl = f"/mnt/{letra_unidad}/{ruta_sin_unidad}"
        return ruta_wsl
    else:
        # If no drive letter pattern is found (e.g. it's already a WSL-like path or a relative path)
        # return it as is, or handle as an error if preferred.
        # For now, returning as is, assuming it might be a path already formatted or not needing conversion.
        return ruta_convertida

def obtener_usuario_wsl():
    """
    Obtiene el nombre de usuario actual dentro de WSL ejecutando 'wsl.exe whoami'.
    Retorna el nombre de usuario como string si es exitoso, None en caso de error.
    """
    try:
        proceso_wsl = subprocess.run(['wsl.exe', 'whoami'], capture_output=True, text=True, check=True, encoding='utf-8')
        usuario = proceso_wsl.stdout.strip()
        return usuario
    except FileNotFoundError:
        print("Error: 'wsl.exe' no encontrado. Asegúrate de que WSL esté instalado y en el PATH.")
        # Podrías mostrar esto en la GUI también si fuera necesario
        messagebox.showerror("Error de WSL", "'wsl.exe' no encontrado. Asegúrate de que WSL esté instalado y en el PATH del sistema.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error al ejecutar 'wsl whoami': {e.stderr}")
        # Podrías mostrar esto en la GUI también
        messagebox.showerror("Error de WSL", f"Error al obtener usuario de WSL: {e.stderr.strip()}")
        return None
    except Exception as e: # Captura general para otros posibles errores
        print(f"Error inesperado al obtener usuario de WSL: {e}")
        messagebox.showerror("Error inesperado", f"Error inesperado al obtener usuario de WSL: {e}")
        return None

def generar_nombre_analisis_por_defecto():
    """Genera un nombre de análisis por defecto basado en la fecha y hora actual."""
    return datetime.datetime.now().strftime("Analisis_%Y%m%d_%H%M%S")

def extraer_nombre_analisis_de_fastq(nombre_archivo_fastq):
    """
    Intenta extraer el patrón 'IVIC-XXXXXXX' del nombre de archivo FASTQ.
    Ej: 'IVIC-1524503_S2_L001_R1_001.fastq.gz' -> 'IVIC-1524503'
    """
    if not nombre_archivo_fastq:
        return "" # O manejar como prefieras, quizás llamar a generar_nombre_analisis_por_defecto()

    nombre_base = os.path.basename(nombre_archivo_fastq)

    # Intentar extraer la parte antes del primer guion bajo
    indice_guion = nombre_base.find('_')

    if indice_guion != -1:
        parte_nombre = nombre_base[:indice_guion]
    else:
        # Si no hay guion bajo, quitar extensiones comunes de fastq
        # Ordenar las extensiones de más larga a más corta para evitar problemas con reemplazos parciales (ej. .fastq.gz vs .gz)
        extensiones_a_quitar = ['.fastq.gz', '.fq.gz', '.fastq', '.fq']
        parte_nombre = nombre_base
        for ext in extensiones_a_quitar:
            if parte_nombre.endswith(ext):
                parte_nombre = parte_nombre[:-len(ext)]
                break # Solo quitar una extensión

    fecha_hoy = datetime.datetime.now().strftime("%Y%m%d")

    if not parte_nombre: # Si después de todo, parte_nombre está vacía (ej. "_algo.fastq.gz")
        # Usar un nombre genérico o el nombre base original sin la primera parte de la extensión
        # Intenta quitar extensiones conocidas y tomar la primera parte si hay puntos.
        temp_nombre = nombre_base
        for ext in ['.fastq.gz', '.fq.gz', '.fastq', '.fq']: # Lista de extensiones comunes
            if temp_nombre.endswith(ext):
                temp_nombre = temp_nombre[:-len(ext)]
                break
        parte_nombre = temp_nombre.split('.')[0] # Tomar la parte antes del primer punto restante

        if not parte_nombre: # Si aún está vacío (caso muy extremo, ej. ".fastq.gz")
             return generar_nombre_analisis_por_defecto() # Usar nombre por defecto basado en fecha/hora completa


    return f"{parte_nombre}_{fecha_hoy}"


def seleccionar_fastq_archivo(lectura_num):
    """
    Abre un cuadro de diálogo para que el usuario elija un archivo FASTQ.
    Actualiza la variable global y la etiqueta correspondiente.
    Si es la Lectura 1, intenta auto-rellenar el nombre del análisis.
    """
    global RUTA_FASTQ_LECTURA1, RUTA_FASTQ_LECTURA2, label_fastq1_seleccionado, label_fastq2_seleccionado, entrada_nombre_analisis

    archivo_seleccionado = filedialog.askopenfilename(
        title=f"Selecciona el archivo FASTQ de Lectura {lectura_num}",
        filetypes=[("Archivos FASTQ", "*.fastq *.fq *.fastq.gz *.fq.gz"), ("Todos los archivos", "*.*")]
    )
    if archivo_seleccionado:
        if lectura_num == 1:
            RUTA_FASTQ_LECTURA1 = archivo_seleccionado
            label_fastq1_seleccionado.config(text=f"Lectura 1: {os.path.basename(RUTA_FASTQ_LECTURA1)}")

            # Intentar rellenar el nombre del análisis automáticamente
            nombre_sugerido = extraer_nombre_analisis_de_fastq(os.path.basename(RUTA_FASTQ_LECTURA1))
            if nombre_sugerido:
                entrada_nombre_analisis.delete(0, tk.END) # Borra el contenido actual
                entrada_nombre_analisis.insert(0, nombre_sugerido) # Inserta el nombre sugerido
        elif lectura_num == 2:
            RUTA_FASTQ_LECTURA2 = archivo_seleccionado
            label_fastq2_seleccionado.config(text=f"Lectura 2: {os.path.basename(RUTA_FASTQ_LECTURA2)}")


def update_gui_with_result(final_output_log, es_ejecucion_exitosa):
    # global necesarios para los widgets que SÍ se modifican aquí
    global output_text, boton_ejecutar_wsl, label_estado_progreso, progress_bar, ventana

    if not output_text: # Comprobación mínima
        print("Error: output_text no está disponible.")
        print(final_output_log)
        return

    output_text.config(state=tk.NORMAL)
    output_text.delete(1.0, tk.END) # Siempre borra el contenido anterior del log
    output_text.insert(tk.END, str(final_output_log) + "\n") # Muestra el log final del pipeline, asegurar newline
    output_text.config(state=tk.DISABLED)

    if boton_ejecutar_wsl:
        boton_ejecutar_wsl.config(state=tk.NORMAL) # Siempre re-habilita el botón

    if label_estado_progreso:
        if es_ejecucion_exitosa:
            label_estado_progreso.config(text="Proceso completado con éxito.")
        else:
            label_estado_progreso.config(text="Proceso finalizado con errores.")

    if progress_bar:
        progress_bar['value'] = 100 if es_ejecucion_exitosa else 0 # 100% en éxito, 0 en error

def update_progress_status(message, step_value):
    """
    Actualiza la etiqueta de estado y la barra de progreso.
    Esta función es segura para llamar desde un hilo secundario.
    """
    if label_estado_progreso and progress_bar and ventana:
        ventana.after(0, label_estado_progreso.config, {'text': f"Estado: {message}"})
        ventana.after(0, progress_bar.config, {'value': step_value})
        ventana.after(0, ventana.update_idletasks) # Fuerza la actualización de la GUI

def actualizar_indicador_paso(indice_paso, estado):
    global widgets_indicadores_pasos, ventana # Necesario si no están ya en el scope global de la función

    simbolos_estado = {
        "pendiente": "[ ]",
        "en_progreso": "[⌛]", # Puedes usar otros símbolos si prefieres, ej. "...", "Ejecutando..."
        "completado": "[✔]",
        "fallido": "[❌]"
    }
    simbolo_a_usar = simbolos_estado.get(estado, "[?]") # Default a "?" si el estado es desconocido

    if ventana and widgets_indicadores_pasos and 0 <= indice_paso < len(widgets_indicadores_pasos):
        widget_indicador = widgets_indicadores_pasos[indice_paso]
        # Ejecutar la actualización en el hilo principal de Tkinter
        ventana.after(0, lambda w=widget_indicador, s=simbolo_a_usar: w.config(text=s))
    else:
        # Opcional: imprimir un error si la ventana o los widgets no están listos
        print(f"Error: No se pudo actualizar el indicador para el paso {indice_paso} al estado {estado}. Ventana o widgets no disponibles.")

def reiniciar_campos_gui():
    # Asegurarse de que los widgets globales sean accesibles
    global RUTA_FASTQ_LECTURA1, RUTA_FASTQ_LECTURA2
    global entrada_nombre_analisis, label_fastq1_seleccionado, label_fastq2_seleccionado
    global widgets_indicadores_pasos, label_estado_progreso, progress_bar, output_text
    # También 'generar_nombre_analisis_por_defecto' y 'actualizar_indicador_paso' deben ser accesibles.

    # Limpiar y resetear el campo de nombre del análisis
    if entrada_nombre_analisis:
        entrada_nombre_analisis.delete(0, tk.END)
        entrada_nombre_analisis.insert(0, generar_nombre_analisis_por_defecto())

    # Resetear etiquetas de selección de archivos FASTQ
    if label_fastq1_seleccionado:
        label_fastq1_seleccionado.config(text="Lectura 1: Ningún archivo seleccionado")
    if label_fastq2_seleccionado:
        label_fastq2_seleccionado.config(text="Lectura 2: Ningún archivo seleccionado")

    # Resetear variables globales de ruta FASTQ
    RUTA_FASTQ_LECTURA1 = ""
    RUTA_FASTQ_LECTURA2 = ""

    # Reiniciar indicadores de pasos del workflow a "pendiente"
    if widgets_indicadores_pasos:
        for i in range(len(widgets_indicadores_pasos)):
            actualizar_indicador_paso(i, "pendiente")

    # Actualizar etiqueta de estado y barra de progreso
    if label_estado_progreso:
        label_estado_progreso.config(text="Estado: Listo para iniciar")
    if progress_bar:
        progress_bar['value'] = 0

    # Limpiar el área de texto de salida
    if output_text:
        output_text.config(state=tk.NORMAL)
        output_text.delete(1.0, tk.END)
        output_text.config(state=tk.DISABLED)

def _run_wsl_command_thread():
    global RUTA_WSL_DIR_TRABAJO_ACTUAL, RUTA_WSL_FASTQ_LECTURA1, RUTA_WSL_FASTQ_LECTURA2
    global RUTA_WSL_ARCHIVO_BAM_PIPELINE, RUTA_WSL_ARCHIVO_VCF_PIPELINE
    """
    Contiene la lógica para crear el directorio de trabajo en WSL,
    copiar los FASTQ, ejecutar el pipeline y copiar el resultado.
    """
    full_output = ""
    paso_actual_indice = -1 # Para rastrear el paso actual en caso de error
    ejecucion_exitosa = False # Nuevo flag para el estado final
    tiempo_inicio_pipeline = datetime.datetime.now()

    # Obtener el nombre del análisis del campo de entrada
    nombre_analisis_input = entrada_nombre_analisis.get().strip()
    if not nombre_analisis_input:
        nombre_analisis_input = generar_nombre_analisis_por_defecto()
        full_output += f"Advertencia: No se ingresó un nombre de análisis. Usando '{nombre_analisis_input}' por defecto.\n"

    # Definir el directorio de trabajo en WSL para este análisis
    RUTA_WSL_DIR_TRABAJO_ACTUAL = os.path.join(RUTA_BASE_ANALISIS_WSL, nombre_analisis_input).replace("\\", "/")

    # Definir las rutas de los FASTQ y los archivos de salida dentro de este directorio de trabajo de WSL
    RUTA_WSL_FASTQ_LECTURA1 = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, os.path.basename(RUTA_FASTQ_LECTURA1)).replace("\\", "/")
    RUTA_WSL_FASTQ_LECTURA2 = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, os.path.basename(RUTA_FASTQ_LECTURA2)).replace("\\", "/")

    # Nombres de archivos de salida del pipeline (ajusta estos si tu pipeline usa otros nombres)
    # Usamos el nombre_analisis_input para los nombres de los archivos de salida
    NOMBRE_ARCHIVO_VCF_PIPELINE = f"{nombre_analisis_input}.chr7.raw_variants.vcf.gz"
    NOMBRE_ARCHIVO_BAM_PIPELINE = f"{nombre_analisis_input}.bam" # BAM final

    RUTA_WSL_ARCHIVO_VCF_PIPELINE = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "vcf", NOMBRE_ARCHIVO_VCF_PIPELINE).replace("\\", "/")
    RUTA_WSL_ARCHIVO_BAM_PIPELINE = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam", NOMBRE_ARCHIVO_BAM_PIPELINE).replace("\\", "/") # Assuming RUTA_WSL_ARCHIVO_BAM_PIPELINE was also intended to be in bam subdir, based on previous step logic for other BAMs. If not, this line is an unintentional change.

    try:
        update_progress_status("Iniciando proceso...", 0)

        # Paso 1: Crear el directorio de trabajo específico para este análisis en WSL
        full_output += f"Creando directorio de trabajo en WSL: {RUTA_WSL_DIR_TRABAJO_ACTUAL}\n"
        comando_mkdir_wsl_trabajo = ['wsl.exe', 'mkdir', '-p', RUTA_WSL_DIR_TRABAJO_ACTUAL]
        subprocess.run(comando_mkdir_wsl_trabajo, check=True, capture_output=True, text=True, encoding='utf-8')

        # Crear subdirectorio BAM en WSL
        path_bam_wsl = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam").replace("\\", "/")
        comando_mkdir_bam = ['wsl.exe', 'mkdir', '-p', path_bam_wsl]
        subprocess.run(comando_mkdir_bam, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Creado subdirectorio BAM en WSL: {path_bam_wsl}\n"

        # Crear subdirectorio VCF en WSL
        path_vcf_wsl = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "vcf").replace("\\", "/")
        comando_mkdir_vcf = ['wsl.exe', 'mkdir', '-p', path_vcf_wsl]
        subprocess.run(comando_mkdir_vcf, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Creado subdirectorio VCF en WSL: {path_vcf_wsl}\n"

        update_progress_status("Copiando archivos FASTQ a WSL...", 10)
        full_output += "\nCopiando archivos FASTQ a WSL...\n"

        # Copiar Lectura 1
        comando_copia_fastq1 = ['wsl.exe', 'cp',
                                 RUTA_FASTQ_LECTURA1.replace("\\", "/").replace("C:", "/mnt/c"), # Ruta de Windows para WSL
                                 RUTA_WSL_FASTQ_LECTURA1]
        subprocess.run(comando_copia_fastq1, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Copiado '{os.path.basename(RUTA_FASTQ_LECTURA1)}' a WSL: {RUTA_WSL_FASTQ_LECTURA1}\n"

        # Copiar Lectura 2
        comando_copia_fastq2 = ['wsl.exe', 'cp',
                                 RUTA_FASTQ_LECTURA2.replace("\\", "/").replace("C:", "/mnt/c"), # Ruta de Windows para WSL
                                 RUTA_WSL_FASTQ_LECTURA2]
        subprocess.run(comando_copia_fastq2, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Copiado '{os.path.basename(RUTA_FASTQ_LECTURA2)}' a WSL: {RUTA_WSL_FASTQ_LECTURA2}\n"

        # --- Ejecución del Pipeline en WSL ---
        full_output += "\n--- Iniciando Pipeline de Análisis de Variantes en WSL ---\n"

        # Define rutas temporales para archivos intermedios si tu pipeline los necesita
        # Por ejemplo, para el BAM alineado antes de sort/markduplicates
        RUTA_WSL_BAM_ALIGN_UNSORTED = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam", f"{nombre_analisis_input}_aligned.bam").replace("\\", "/")
        RUTA_WSL_BAM_ALIGNED_SORTED = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam", f"{nombre_analisis_input}_sorted.bam").replace("\\", "/")
        RUTA_WSL_BAM_MD = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam", f"{nombre_analisis_input}_md.bam").replace("\\", "/")
        RUTA_WSL_BAM_RG = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam", f"{nombre_analisis_input}_rg.bam").replace("\\", "/")
        # Asignar el BAM final a la variable global que se copiará
        RUTA_WSL_ARCHIVO_BAM_PIPELINE = RUTA_WSL_BAM_RG # El BAM final será el que tiene los grupos de lectura

        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        # ¡¡¡ ATENCIÓN: REEMPLAZA ESTOS COMANDOS DE SIMULACIÓN CON TUS COMANDOS REALES !!!
        # Asegúrate de tener BWA, Samtools y GATK instalados y en el PATH de tu usuario 'germanpet' en WSL.
        # Ajusta las rutas a tu genoma de referencia (e.g., /path/to/your/reference.fasta)

        # Paso 3.1: Alineamiento (BWA mem)
        paso_actual_indice = 0
        actualizar_indicador_paso(paso_actual_indice, "en_progreso")
        update_progress_status("Ejecutando Alineamiento (BWA mem)...", 20)
        full_output += "\n[Paso 3.1/7] Alineamiento (BWA mem)...\n"
        # Comando real para BWA mem y samtools view:
        comando_alineamiento = [
            'wsl.exe', 'bash', '-c',
            f"bwa mem -t 20 {RUTA_GENOMA_REFERENCIA_WSL} {RUTA_WSL_FASTQ_LECTURA1} {RUTA_WSL_FASTQ_LECTURA2} | samtools view -Sb - > {RUTA_WSL_BAM_ALIGN_UNSORTED}"
        ]
        subprocess.run(comando_alineamiento, check=True, capture_output=True, text=True, encoding='utf-8')
        actualizar_indicador_paso(paso_actual_indice, "completado")
        full_output += "Alineamiento completado.\n"

        # Paso 3.2: Ordenar BAM (samtools sort)
        paso_actual_indice = 1
        actualizar_indicador_paso(paso_actual_indice, "en_progreso")
        update_progress_status("Ordenando BAM (samtools sort)...", 30)
        full_output += "\n[Paso 3.2/7] Ordenar BAM (samtools sort)...\n"
        # Comando real para samtools sort:
        comando_sort_bam = [
            'wsl.exe', 'samtools', 'sort', '-o', RUTA_WSL_BAM_ALIGNED_SORTED, RUTA_WSL_BAM_ALIGN_UNSORTED
        ]
        subprocess.run(comando_sort_bam, check=True, capture_output=True, text=True, encoding='utf-8')
        actualizar_indicador_paso(paso_actual_indice, "completado")
        full_output += "Ordenar BAM completado.\n"

        # Paso 3.3: Marcar duplicados (GATK MarkDuplicates)
        paso_actual_indice = 2
        actualizar_indicador_paso(paso_actual_indice, "en_progreso")
        update_progress_status("Marcando duplicados (GATK MarkDuplicates)...", 45)
        full_output += "\n[Paso 3.3/7] Marcar duplicados (GATK MarkDuplicates)...\n"
        # Definir path para el archivo de métricas de duplicados
        RUTA_WSL_METRICAS_DEDUP = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam", f"{nombre_analisis_input}.dedup_metrics.txt").replace("\\", "/")
        # Comando real para GATK MarkDuplicates:
        comando_markduplicates = [
            'wsl.exe', 'gatk', 'MarkDuplicates',
            '-I', RUTA_WSL_BAM_ALIGNED_SORTED,
            '-O', RUTA_WSL_BAM_MD,
            '-M', RUTA_WSL_METRICAS_DEDUP
        ]
        subprocess.run(comando_markduplicates, check=True, capture_output=True, text=True, encoding='utf-8')
        actualizar_indicador_paso(paso_actual_indice, "completado")
        full_output += "Marcado de duplicados completado.\n"

        # Paso 3.4: Añadir grupos de lectura (samtools addreplacerg)
        paso_actual_indice = 3
        actualizar_indicador_paso(paso_actual_indice, "en_progreso")
        update_progress_status("Añadiendo grupos de lectura (samtools addreplacerg)...", 60)
        full_output += "\n[Paso 3.4/7] Añadir grupos de lectura (samtools addreplacerg)...\n"
        # Definir el encabezado del grupo de lectura
        read_group_header = f"@RG\tID:rg1\tSM:{nombre_analisis_input}\tLB:lib1\tPL:ILLUMINA"
        # Comando real para samtools addreplacerg:
        comando_add_rg = [
            'wsl.exe', 'samtools', 'addreplacerg',
            '-r', read_group_header,
            RUTA_WSL_BAM_MD,
            '-o', RUTA_WSL_BAM_RG
        ]
        subprocess.run(comando_add_rg, check=True, capture_output=True, text=True, encoding='utf-8')
        actualizar_indicador_paso(paso_actual_indice, "completado")
        full_output += "Añadir grupos de lectura completado.\n"

        # Paso 3.5: Indexar BAM (samtools index)
        paso_actual_indice = 4
        actualizar_indicador_paso(paso_actual_indice, "en_progreso")
        update_progress_status("Indexando BAM (samtools index)...", 70)
        full_output += "\n[Paso 3.5/7] Indexar BAM (samtools index)...\n"
        # Comando real para samtools index:
        comando_index_bam = [
            'wsl.exe', 'samtools', 'index',
            RUTA_WSL_BAM_RG  # Input BAM file to index
        ]
        subprocess.run(comando_index_bam, check=True, capture_output=True, text=True, encoding='utf-8')
        actualizar_indicador_paso(paso_actual_indice, "completado")
        full_output += "Indexación de BAM completada.\n"

        # Paso 3.6: Llamada de variantes (GATK HaplotypeCaller - chr7)
        paso_actual_indice = 5
        actualizar_indicador_paso(paso_actual_indice, "en_progreso")
        update_progress_status("Llamada de variantes (GATK HaplotypeCaller - chr7)...", 80)
        full_output += "\n[Paso 3.6/7] Llamada de variantes (GATK HaplotypeCaller - chr7)...\n"
        # Comando real para GATK HaplotypeCaller:
        comando_haplotypecaller = [
            'wsl.exe', 'gatk', 'HaplotypeCaller',
            '-R', RUTA_GENOMA_REFERENCIA_WSL,
            '-I', RUTA_WSL_BAM_RG,
            '-O', RUTA_WSL_ARCHIVO_VCF_PIPELINE,
            '-L', 'chr7'
        ]
        subprocess.run(comando_haplotypecaller, check=True, capture_output=True, text=True, encoding='utf-8')
        actualizar_indicador_paso(paso_actual_indice, "completado")
        full_output += "Llamada de variantes completada.\n"

        # Paso 3.7: Anotación y Filtrado (GATK VariantAnnotator y VariantFiltration)
        # GATK VariantAnnotator a menudo se puede integrar con HaplotypeCaller o ser un paso separado.
        # GATK VariantFiltration se usa para filtrar las variantes después de la llamada.
        # Aquí los simulamos como un solo paso para simplificar.

        paso_actual_indice = 6 # This index might represent the combined Annotation & Filtration step
        actualizar_indicador_paso(paso_actual_indice, "en_progreso") # Mark as in progress

        # --- Paso 3.7a: Anotación de Variantes (GATK VariantAnnotator) ---
        update_progress_status("Anotación de Variantes (GATK VariantAnnotator)...", 90) # Progress bar for this sub-step
        full_output += "\n[Paso 3.7a/7] Anotación de Variantes (GATK VariantAnnotator)...\n"

        RUTA_WSL_VCF_ANOTADO = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "vcf", f"{nombre_analisis_input}.chr7.annotated.vcf.gz").replace("\\", "/")

        comando_variant_annotator = [
            'wsl.exe', 'gatk', 'VariantAnnotator',
            '-R', RUTA_GENOMA_REFERENCIA_WSL,
            '-V', RUTA_WSL_ARCHIVO_VCF_PIPELINE, # Input: VCF from HaplotypeCaller
            '-A', 'QualByDepth',
            '-A', 'FisherStrand',
            '-A', 'StrandOddsRatio',
            '-A', 'RMSMappingQuality',
            '-A', 'MappingQualityRankSumTest',
            '-A', 'ReadPosRankSumTest',
            '-O', RUTA_WSL_VCF_ANOTADO      # Output: Annotated VCF
        ]

        annotator_result = subprocess.run(comando_variant_annotator, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Salida de VariantAnnotator:\n{annotator_result.stdout.strip()}\n"
        if annotator_result.stderr:
            full_output += f"Errores/Advertencias de VariantAnnotator:\n{annotator_result.stderr.strip()}\n"
        full_output += "Anotación de variantes completada.\n"

        # Definir path para el VCF filtrado
        RUTA_WSL_VCF_FILTRADO = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "vcf", f"{nombre_analisis_input}.chr7.filtered.vcf.gz").replace("\\", "/")

        # --- Paso 3.7b: Filtrado de Variantes (GATK VariantFiltration) ---
        full_output += "\n[Paso 3.7b/7] Filtrado de Variantes (GATK VariantFiltration)...\n"
        # update_progress_status para VariantFiltration si se desea un control más fino de la barra de progreso

        comando_variant_filtration = [
            'wsl.exe', 'gatk', 'VariantFiltration',
            '-V', RUTA_WSL_VCF_ANOTADO, # Input: Annotated VCF from VariantAnnotator
            '-filter', "QD < 2.0", '--filter-name', "LowQD",
            '-filter', "FS > 60.0", '--filter-name', "StrandBiasFS", # Renombrado para evitar colisión con SOR
            '-filter', "SOR > 3.0", '--filter-name', "StrandBiasSOR",# Renombrado para evitar colisión con FS
            '-filter', "MQ < 40.0", '--filter-name', "LowMQ",
            '-filter', "MQRankSum < -12.5", '--filter-name', "MQRankSum", # Eliminado '&& MQRankSum != null' ya que GATK maneja esto.
            '-filter', "ReadPosRankSum < -8.0", '--filter-name', "ReadPosRankSum", # Eliminado '&& ReadPosRankSum != null'
            '-O', RUTA_WSL_VCF_FILTRADO # Output: Filtered VCF
        ]

        filtration_result = subprocess.run(comando_variant_filtration, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Salida de VariantFiltration:\n{filtration_result.stdout.strip()}\n"
        if filtration_result.stderr:
            full_output += f"Errores/Advertencias de VariantFiltration:\n{filtration_result.stderr.strip()}\n"
        full_output += "Filtrado de variantes completado.\n"

        # Actualizar la variable global que indica el VCF final a copiar
        # La declaración global ya está al inicio de la función
        RUTA_WSL_ARCHIVO_VCF_PIPELINE = RUTA_WSL_VCF_FILTRADO
        full_output += f"El archivo VCF final para copiar es ahora: {RUTA_WSL_ARCHIVO_VCF_PIPELINE}\n"

        # Ahora que todos los sub-pasos de 3.7 (Anotación y Filtrado) están completos:
        actualizar_indicador_paso(paso_actual_indice, "completado") # Marcar el paso general 6 como completado
        full_output += "Paso de Anotación y Filtrado completado.\n"
        full_output += "\n--- Pipeline completado en WSL ---\n"

        # Opcional: Mostrar los archivos de resultado creados en WSL
        comando_ls_wsl_output = ['wsl.exe', 'ls', '-l', RUTA_WSL_DIR_TRABAJO_ACTUAL]
        ls_output_result = subprocess.run(comando_ls_wsl_output, capture_output=True, text=True, check=False, encoding='utf-8')
        full_output += f"Listado de '{RUTA_WSL_DIR_TRABAJO_ACTUAL}' en WSL:\n{ls_output_result.stdout.strip()}\n\n"

        # Paso 4: Copiar BAM y VCF a las carpetas 'bam' y 'vcf' en el directorio de origen de los FASTQ
        update_progress_status("Copiando resultados finales a carpetas 'bam' y 'vcf'...", 95)
        full_output += "Copiando BAM/VCF a carpetas 'bam' y 'vcf' en el origen de los FASTQ...\n"

        # Obtener el directorio de origen de los FASTQ
        dir_origen_fastqs = os.path.dirname(RUTA_FASTQ_LECTURA1)

        # Crear la carpeta 'bam' en el origen de los FASTQ (Windows)
        carpeta_bam_origen = os.path.join(dir_origen_fastqs, "bam")
        os.makedirs(carpeta_bam_origen, exist_ok=True)
        full_output += f"Carpeta de destino BAM (Windows) creada/existente en: {carpeta_bam_origen}\n"

        # Copiar contenido de la carpeta 'bam' de WSL a Windows
        full_output += "\nCopiando contenido de la carpeta 'bam' de WSL a Windows...\n"
        path_wsl_bam_source_folder = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam", ".").replace("\\", "/")
        path_windows_bam_dest_folder_converted = convertir_ruta_windows_a_wsl(carpeta_bam_origen)

        comando_copia_bam_folder = ['wsl.exe', 'cp', '-r', path_wsl_bam_source_folder, path_windows_bam_dest_folder_converted]
        copy_bam_folder_result = subprocess.run(comando_copia_bam_folder, capture_output=True, text=True, check=True, encoding='utf-8')
        full_output += f"Contenido de la carpeta BAM copiado a: {carpeta_bam_origen}\n"
        if copy_bam_folder_result.stdout:
            full_output += f"Salida de copia de carpeta BAM: {copy_bam_folder_result.stdout.strip()}\n"
        if copy_bam_folder_result.stderr:
            full_output += f"Errores/Advertencias de copia de carpeta BAM: {copy_bam_folder_result.stderr.strip()}\n"

        # Crear la carpeta 'vcf' en el origen de los FASTQ (Windows)
        carpeta_vcf_origen = os.path.join(dir_origen_fastqs, "vcf")
        os.makedirs(carpeta_vcf_origen, exist_ok=True)
        full_output += f"Carpeta de destino VCF (Windows) creada/existente en: {carpeta_vcf_origen}\n"

        # Copiar contenido de la carpeta 'vcf' de WSL a Windows
        full_output += "\nCopiando contenido de la carpeta 'vcf' de WSL a Windows...\n"
        path_wsl_vcf_source_folder = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "vcf", ".").replace("\\", "/")
        path_windows_vcf_dest_folder_converted = convertir_ruta_windows_a_wsl(carpeta_vcf_origen)

        comando_copia_vcf_folder = ['wsl.exe', 'cp', '-r', path_wsl_vcf_source_folder, path_windows_vcf_dest_folder_converted]
        copy_vcf_folder_result = subprocess.run(comando_copia_vcf_folder, capture_output=True, text=True, check=True, encoding='utf-8')
        full_output += f"Contenido de la carpeta VCF copiado a: {carpeta_vcf_origen}\n"
        if copy_vcf_folder_result.stdout:
            full_output += f"Salida de copia de carpeta VCF: {copy_vcf_folder_result.stdout.strip()}\n"
        if copy_vcf_folder_result.stderr:
            full_output += f"Errores/Advertencias de copia de carpeta VCF: {copy_vcf_folder_result.stderr.strip()}\n"

        update_progress_status("Proceso completado con éxito.", 100)
        full_output += "\n¡Proceso de análisis y copia de resultados completado exitosamente!\n"

        tiempo_fin_pipeline = datetime.datetime.now()
        duracion_pipeline = tiempo_fin_pipeline - tiempo_inicio_pipeline
        segundos_totales = duracion_pipeline.total_seconds()
        minutos = int(segundos_totales // 60)
        segundos = int(segundos_totales % 60)
        full_output += f"\nTiempo total de ejecución del pipeline: {minutos} minuto(s) y {segundos} segundo(s).\n"

        ejecucion_exitosa = True

    except subprocess.CalledProcessError as e:
        full_output = f"Error al ejecutar comando WSL (código: {e.returncode}):\n{e.stderr.strip()}\n"
        full_output += f"Comando fallido: {' '.join(e.cmd)}\n"
        if "No such file or directory" in e.stderr:
            full_output += "\n**SUGERENCIA:** Verifica que los archivos o directorios en WSL existen, especialmente las rutas de tu pipeline, genoma de referencia, o los archivos de entrada/salida."
        if paso_actual_indice != -1:
            actualizar_indicador_paso(paso_actual_indice, "fallido")
        update_progress_status("Proceso fallido.", 0) # Reinicia la barra en caso de error
    except FileNotFoundError:
        full_output = (
            "Error: 'wsl.exe' no se encontró en tu sistema.\n\n"
            "**Causas posibles:**\n"
            "1. WSL no está instalado en tu computadora.\n"
            "2. WSL está instalado, pero el ejecutable 'wsl.exe' no está en el 'PATH' del sistema.\n\n"
            "**Soluciones sugeridas:**\n"
            "1. **Instala WSL:** Abre PowerShell como administrador y ejecuta `wsl --install`.\n"
            "2. **Asegura que tu distribución de Ubuntu esté instalada:** Si WSL está instalado, verifica que tengas una distribución de Linux (ej. Ubuntu) instalada y funcionando. Puedes verificar con `wsl -l -v`.\n"
            "3. **Reinicia tu sistema:** A veces, un reinicio después de la instalación de WSL puede resolver problemas con el PATH.\n"
            "4. **Verifica tu PATH:** Asegúrate de que `C:\\Windows\\System32` esté en tu variable de entorno PATH."
        )
        # No hay un paso específico del pipeline que falló aquí, así que no llamamos a actualizar_indicador_paso
        update_progress_status("Error: WSL no encontrado.", 0)
    except Exception as e:
        full_output = f"Ocurrió un error inesperado en Python: {e}"
        if paso_actual_indice != -1:
            actualizar_indicador_paso(paso_actual_indice, "fallido")
        update_progress_status("Proceso fallido (error inesperado).", 0)
    finally:
        if ventana:
            ventana.after(0, update_gui_with_result, full_output, ejecucion_exitosa)
        else:
            print("La ventana Tkinter no está inicializada. No se pudo actualizar la GUI.")
            print(full_output)


# --- Función principal que configura la GUI ---
def main():
    global ventana, boton_ejecutar_wsl, output_text
    global label_fastq1_seleccionado, label_fastq2_seleccionado, entrada_nombre_analisis
    global label_estado_progreso, progress_bar

    ventana = tk.Tk()
    ventana.title("Análisis de Variantes en CFTR")
    ventana.geometry("950x850") # Un poco más grande para el workflow y progreso
    ventana.resizable(True, True)

    # --- Menú superior ---
    menubar = tk.Menu(ventana)

    archivo_menu = tk.Menu(menubar, tearoff=0)
    archivo_menu.add_command(label="Salir", command=ventana.destroy) # Use ventana.destroy
    menubar.add_cascade(label="Archivo", menu=archivo_menu)

    ayuda_menu = tk.Menu(menubar, tearoff=0)

    creditos_completos = (
        "Análisis de Variantes en CFTR\n\n"
        "Versión 1.1.1\n\n"
        "© 2025 GBSCorelab. Todos los derechos reservados.\n"
        "Desarrollador: Germán Peña\n"
        "germanpet@gmail.com (Soporte y Café)"
    )
    ayuda_menu.add_command(label="Acerca de...", command=lambda: messagebox.showinfo( # Added ... a Acerca de
        "Acerca de Análisis de Variantes en CFTR",
        creditos_completos
    ))

    instrucciones_texto = (
        "1. Ingresa un nombre para el análisis o usa el sugerido del FASTQ R1.\n"
        "2. Selecciona los archivos de Lectura FASTQ (R1 y R2).\n"
        "3. Haz clic en 'Iniciar Análisis' para ejecutar el pipeline.\n"
        "4. Los resultados (carpetas 'bam' y 'vcf') se guardarán junto a tus archivos FASTQ de origen.\n"
        "5. Usa 'Reiniciar GUI' para limpiar los campos para un nuevo análisis."
    )
    ayuda_menu.add_command(label="Instrucciones", command=lambda: messagebox.showinfo(
        "Instrucciones de Uso",
        instrucciones_texto
    ))
    menubar.add_cascade(label="Ayuda", menu=ayuda_menu)

    ventana.config(menu=menubar)
    # --- Fin Menú superior ---

    frame = ttk.Frame(ventana, padding="15")
    frame.pack(fill='both', expand=True)

    # --- Sección de Logos ---
    frame_superior = ttk.Frame(frame) # Crear dentro del frame principal con padding
    frame_superior.pack(side='top', fill='x', anchor='n', pady=(0,10)) # pady para separar de lo de abajo

    frame_logos_derecha = ttk.Frame(frame_superior)
    frame_logos_derecha.pack(side='right')

    # Cargar y mostrar logo_ivegen.png (aparecerá más a la derecha)
    try:
        ventana.logo_ivegen_img = tk.PhotoImage(file="logo_ivegen.png")
        label_logo_ivegen = ttk.Label(frame_logos_derecha, image=ventana.logo_ivegen_img)
        label_logo_ivegen.pack(side='right', padx=5, pady=5)
    except tk.TclError as e:
        print(f"Error al cargar logo_ivegen.png: {e}. Asegúrate que el archivo está en el mismo directorio que el script.")
        # Opcional: mostrar un placeholder o nada

    # Cargar y mostrar logo_gscorelab.png (aparecerá a la izquierda de ivegen)
    try:
        ventana.logo_gscorelab_img = tk.PhotoImage(file="logo_gscorelab.png")
        label_logo_gscorelab = ttk.Label(frame_logos_derecha, image=ventana.logo_gscorelab_img)
        label_logo_gscorelab.pack(side='right', padx=5, pady=5) # Empaquetado antes para estar a la izquierda
    except tk.TclError as e:
        print(f"Error al cargar logo_gscorelab.png: {e}. Asegúrate que el archivo está en el mismo directorio que el script.")
        # Opcional: mostrar un placeholder o nada
    # --- Fin Sección de Logos ---

    # Sección Nombre del Análisis
    label_nombre_analisis_instruccion = ttk.Label(frame, text="1. Ingresa un nombre para este análisis (opcional, se sugiere automáticamente del FASTQ R1):", font=('Helvetica', 11))
    label_nombre_analisis_instruccion.pack(pady=5, anchor='w')

    entrada_nombre_analisis = ttk.Entry(frame, width=50)
    entrada_nombre_analisis.pack(pady=5, anchor='w')
    entrada_nombre_analisis.insert(0, generar_nombre_analisis_por_defecto()) # Nombre por defecto al iniciar

    ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=10)

    # Sección de Selección de Archivos FASTQ
    label_fastq_instruccion = ttk.Label(frame, text="2. Selecciona tus archivos de Lectura FASTQ:", font=('Helvetica', 11))
    label_fastq_instruccion.pack(pady=5, anchor='w')

    frame_fastq_buttons = ttk.Frame(frame)
    frame_fastq_buttons.pack(pady=5, fill='x')

    boton_seleccionar_fastq1 = ttk.Button(frame_fastq_buttons, text="Seleccionar Lectura 1 (R1)", command=lambda: seleccionar_fastq_archivo(1))
    boton_seleccionar_fastq1.pack(side='left', padx=5)

    label_fastq1_seleccionado = ttk.Label(frame_fastq_buttons, text="Lectura 1: Ningún archivo seleccionado", font=('Helvetica', 10), wraplength=700)
    label_fastq1_seleccionado.pack(side='left', fill='x', expand=True)

    frame_fastq_buttons2 = ttk.Frame(frame)
    frame_fastq_buttons2.pack(pady=5, fill='x')

    boton_seleccionar_fastq2 = ttk.Button(frame_fastq_buttons2, text="Seleccionar Lectura 2 (R2)", command=lambda: seleccionar_fastq_archivo(2))
    boton_seleccionar_fastq2.pack(side='left', padx=5)

    label_fastq2_seleccionado = ttk.Label(frame_fastq_buttons2, text="Lectura 2: Ningún archivo seleccionado", font=('Helvetica', 10), wraplength=700)
    label_fastq2_seleccionado.pack(side='left', fill='x', expand=True)

    ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=10)

    # Sección del Workflow
    label_workflow_titulo = ttk.Label(frame, text="3. Workflow de Análisis de Variantes en WSL:", font=('Helvetica', 11, 'bold'))
    label_workflow_titulo.pack(pady=5, anchor='w')

    # Definir los pasos del workflow
    pasos_workflow = [
        "Alineamiento (BWA mem)",
        "Ordenar BAM (samtools sort)",
        "Marcar duplicados (GATK MarkDuplicates)",
        "Añadir grupos de lectura (samtools addreplacerg)",
        "Indexar BAM (samtools index)",
        "Llamada de variantes (GATK HaplotypeCaller - chr7)",
        "Anotación y Filtrado (GATK VariantAnnotator & VariantFiltration)"
    ]

    # Frame para contener los pasos del workflow con indicadores
    frame_workflow_pasos = ttk.Frame(frame)
    frame_workflow_pasos.pack(pady=5, anchor='w', fill='x')

    global widgets_indicadores_pasos # Declarar global para modificarla
    widgets_indicadores_pasos.clear() # Limpiar por si acaso main() se llama múltiples veces (poco probable aquí)

    for i, nombre_paso in enumerate(pasos_workflow):
        frame_paso_individual = ttk.Frame(frame_workflow_pasos)
        frame_paso_individual.pack(anchor='w', fill='x')

        label_indicador = ttk.Label(frame_paso_individual, text="[ ]", font=('Courier New', 10, 'bold'))
        label_indicador.pack(side='left', padx=(0, 5))

        label_nombre_paso_wf = ttk.Label(frame_paso_individual, text=nombre_paso, font=('Helvetica', 10))
        label_nombre_paso_wf.pack(side='left')

        widgets_indicadores_pasos.append(label_indicador)

    # label_workflow_desc = tk.Label(frame, text=workflow_text, justify=tk.LEFT, font=('Helvetica', 10), wraplength=850)
    # label_workflow_desc.pack(pady=5, anchor='w')

    label_info_origen = ttk.Label(frame, text="**NOTA:** Los resultados BAM y VCF se guardarán en subcarpetas 'bam' y 'vcf' junto a tus archivos FASTQ de origen.", font=('Helvetica', 9), foreground='blue', wraplength=850)
    label_info_origen.pack(pady=10, anchor='w') # Aumentado pady para separar

    ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=10)

    # Sección de Ejecución y Progreso
    label_ejecucion_instruccion = ttk.Label(frame, text="4. Ejecuta el pipeline:", font=('Helvetica', 11))
    label_ejecucion_instruccion.pack(pady=5, anchor='w')

    boton_ejecutar_wsl = ttk.Button(frame, text="Iniciar Análisis", command=ejecutar_comando_wsl)
    boton_ejecutar_wsl.pack(pady=10)

    boton_reiniciar_gui = ttk.Button(frame, text="Reiniciar GUI", command=reiniciar_campos_gui)
    boton_reiniciar_gui.pack(pady=5)

    # Indicador de progreso
    label_estado_progreso = ttk.Label(frame, text="Estado: Listo para iniciar", font=('Helvetica', 10, 'italic'))
    label_estado_progreso.pack(pady=5, anchor='w')

    progress_bar = ttk.Progressbar(frame, orient='horizontal', length=800, mode='determinate')
    progress_bar.pack(pady=5)

    # Área de texto para la salida del comando
    output_text = scrolledtext.ScrolledText(
        frame,
        wrap=tk.WORD,
        width=90,
        height=15,
        font=('Courier New', 10),
        background='black',
        foreground='lightgreen',
        state=tk.DISABLED
    )
    output_text.pack(pady=10, fill='both', expand=True)

    # Obtener usuario de WSL y configurar estado del botón de ejecución
    nombre_usuario = obtener_usuario_wsl()
    if nombre_usuario is None:
        messagebox.showerror("Error de Configuración WSL",
                             "No se pudo determinar el nombre de usuario de WSL. "
                             "Asegúrate de que WSL esté instalado y configurado correctamente. "
                             "La funcionalidad de ejecución del pipeline estará deshabilitada.")
        if boton_ejecutar_wsl: # Asegurarse que el botón existe
            boton_ejecutar_wsl.config(state=tk.DISABLED)
        # También podrías deshabilitar otros widgets o mostrar un mensaje persistente en la GUI
    else:
        global USUARIO_WSL_ACTUAL, RUTA_BASE_ANALISIS_WSL, RUTA_GENOMA_REFERENCIA_WSL
        USUARIO_WSL_ACTUAL = nombre_usuario

        # Actualizar rutas globales con el nombre de usuario de WSL
        RUTA_BASE_ANALISIS_WSL = f"/home/{USUARIO_WSL_ACTUAL}/analisis/"
        RUTA_GENOMA_REFERENCIA_WSL = f"/home/{USUARIO_WSL_ACTUAL}/analisis/reference/GRCh38.fa"

        if boton_ejecutar_wsl: # Asegurarse que el botón existe
            boton_ejecutar_wsl.config(state=tk.NORMAL)
        # Opcionalmente, mostrar el usuario y rutas en algún lugar de la GUI si es útil
        print(f"Usuario WSL detectado: {USUARIO_WSL_ACTUAL}") # Para depuración
        print(f"Ruta base de análisis WSL actualizada: {RUTA_BASE_ANALISIS_WSL}") # Para depuración
        print(f"Ruta genoma de referencia WSL actualizada: {RUTA_GENOMA_REFERENCIA_WSL}") # Para depuración

    # Inicializa el estado de la barra de progreso
    progress_bar['value'] = 0

    ventana.mainloop()


# --- Función controladora del botón de ejecución ---
def ejecutar_comando_wsl():
    """
    Esta función es el controlador del botón "Iniciar Análisis".
    Realiza validaciones y lanza el proceso pesado en un hilo secundario.
    """
    global widgets_indicadores_pasos # Acceso a la lista global de widgets indicadores

    if not RUTA_FASTQ_LECTURA1 or not RUTA_FASTQ_LECTURA2:
        messagebox.showerror(
            "Archivos FASTQ Faltantes",
            "Por favor, selecciona ambos archivos FASTQ (Lectura 1 y Lectura 2) antes de iniciar el análisis."
        )
        return

    # Reiniciar todos los indicadores de pasos a "pendiente"
    if widgets_indicadores_pasos: # Verificar que la lista de widgets exista y no esté vacía
        for i in range(len(widgets_indicadores_pasos)):
            actualizar_indicador_paso(i, "pendiente")

    # Deshabilita el botón y prepara el área de texto
    boton_ejecutar_wsl.config(state=tk.DISABLED)
    output_text.config(state=tk.NORMAL)
    output_text.delete(1.0, tk.END)
    output_text.insert(tk.END, "Iniciando análisis... Por favor, espera.\n")
    output_text.config(state=tk.DISABLED)

    label_estado_progreso.config(text="Estado: Iniciando...")
    progress_bar['value'] = 5 # Pequeño progreso inicial

    thread = threading.Thread(target=_run_wsl_command_thread)
    thread.start()


if __name__ == "__main__":
    main()

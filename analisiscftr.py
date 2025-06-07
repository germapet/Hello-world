import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import subprocess
import threading
import os
import datetime
import shutil
import re # Módulo para expresiones regulares

# --- NUEVAS IMPORTACIONES PARA CLINVAR Y REPORTES ---
from Bio import Entrez
import pysam
import csv
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
import xml.etree.ElementTree as ET
# --- FIN NUEVAS IMPORTACIONES ---


# --- Configuración de rutas predeterminadas y variables globales ---
RUTA_FASTQ_LECTURA1 = ""
RUTA_FASTQ_LECTURA2 = ""
NOMBRE_ANALISIS = ""
USUARIO_WSL_ACTUAL = None
RUTA_BASE_ANALISIS_WSL = None
RUTA_GENOMA_REFERENCIA_WSL = None
RUTA_WSL_DIR_TRABAJO_ACTUAL = ""
RUTA_WSL_FASTQ_LECTURA1 = ""
RUTA_WSL_FASTQ_LECTURA2 = ""
RUTA_WSL_ARCHIVO_VCF_PIPELINE = ""
RUTA_WSL_ARCHIVO_BAM_PIPELINE = ""

# --- Variables globales para los widgets de Tkinter (para acceso desde hilos) ---
ventana = None
boton_ejecutar_wsl = None
output_text = None
label_fastq1_seleccionado = None
label_fastq2_seleccionado = None
entrada_nombre_analisis = None
label_estado_progreso = None
progress_bar = None

entrada_id_paciente = None
entrada_medico_solicitante = None # Corregido: debe ser entrada_medico_solicitante
entrada_laboratorio = None

# --- Funciones ---

def convertir_ruta_windows_a_wsl(ruta_windows):
    if not ruta_windows:
        return ""
    ruta_convertida = ruta_windows.replace("\\", "/")
    match = re.match(r"([a-zA-Z]):/", ruta_convertida)
    if match:
        letra_unidad = match.group(1).lower()
        ruta_sin_unidad = ruta_convertida[len(match.group(0)):]
        ruta_wsl = f"/mnt/{letra_unidad}/{ruta_sin_unidad}"
        return ruta_wsl
    else:
        return ruta_convertida

def obtener_usuario_wsl():
    try:
        proceso_wsl = subprocess.run(['wsl.exe', 'whoami'], capture_output=True, text=True, check=True, encoding='utf-8')
        usuario = proceso_wsl.stdout.strip()
        return usuario
    except FileNotFoundError:
        messagebox.showerror("Error de WSL", "'wsl.exe' no encontrado. Asegúrate de que WSL esté instalado y en el PATH del sistema.")
        return None
    except subprocess.CalledProcessError as e:
        messagebox.showerror("Error de WSL", f"Error al obtener usuario de WSL: {e.stderr.strip()}")
        return None
    except Exception as e:
        messagebox.showerror("Error inesperado", f"Error inesperado al obtener usuario de WSL: {e}")
        return None

def generar_nombre_analisis_por_defecto():
    return datetime.datetime.now().strftime("Analisis_%Y%m%d_%H%M%S")

def extraer_nombre_analisis_de_fastq(nombre_archivo_fastq):
    if not nombre_archivo_fastq:
        return ""
    nombre_base = os.path.basename(nombre_archivo_fastq)
    indice_guion = nombre_base.find('_')
    if indice_guion != -1:
        parte_nombre = nombre_base[:indice_guion]
    else:
        extensiones_a_quitar = ['.fastq.gz', '.fq.gz', '.fastq', '.fq']
        parte_nombre = nombre_base
        for ext in extensiones_a_quitar:
            if parte_nombre.endswith(ext):
                parte_nombre = parte_nombre[:-len(ext)]
                break
    fecha_hoy = datetime.datetime.now().strftime("%Y%m%d")
    if not parte_nombre:
        temp_nombre = nombre_base
        for ext in ['.fastq.gz', '.fq.gz', '.fastq', '.fq']:
            if temp_nombre.endswith(ext):
                temp_nombre = temp_nombre[:-len(ext)]
                break
        parte_nombre = temp_nombre.split('.')[0]
        if not parte_nombre:
             return generar_nombre_analisis_por_defecto()
    return f"{parte_nombre}_{fecha_hoy}"

def seleccionar_fastq_archivo(lectura_num):
    global RUTA_FASTQ_LECTURA1, RUTA_FASTQ_LECTURA2, label_fastq1_seleccionado, label_fastq2_seleccionado, entrada_nombre_analisis
    archivo_seleccionado = filedialog.askopenfilename(
        title=f"Selecciona el archivo FASTQ de Lectura {lectura_num}",
        filetypes=[("Archivos FASTQ", "*.fastq *.fq *.fastq.gz *.fq.gz"), ("Todos los archivos", "*.*")]
    )
    if archivo_seleccionado:
        if lectura_num == 1:
            RUTA_FASTQ_LECTURA1 = archivo_seleccionado
            label_fastq1_seleccionado.config(text=f"Lectura 1: {os.path.basename(RUTA_FASTQ_LECTURA1)}")
            nombre_sugerido = extraer_nombre_analisis_de_fastq(os.path.basename(RUTA_FASTQ_LECTURA1))
            if nombre_sugerido:
                entrada_nombre_analisis.delete(0, tk.END)
                entrada_nombre_analisis.insert(0, nombre_sugerido)
        elif lectura_num == 2:
            RUTA_FASTQ_LECTURA2 = archivo_seleccionado
            label_fastq2_seleccionado.config(text=f"Lectura 2: {os.path.basename(RUTA_FASTQ_LECTURA2)}")

def update_gui_with_result(final_output_log, es_ejecucion_exitosa):
    global output_text, boton_ejecutar_wsl, label_estado_progreso, progress_bar, ventana
    if not output_text:
        print("Error: output_text no está disponible.")
        print(final_output_log)
        return
    output_text.config(state=tk.NORMAL)
    output_text.delete(1.0, tk.END)
    output_text.insert(tk.END, str(final_output_log) + "\n")
    output_text.config(state=tk.DISABLED)
    if boton_ejecutar_wsl:
        boton_ejecutar_wsl.config(state=tk.NORMAL)
    if label_estado_progreso:
        if es_ejecucion_exitosa:
            label_estado_progreso.config(text="Proceso completado con éxito.")
        else:
            label_estado_progreso.config(text="Proceso finalizado con errores.")
    if progress_bar:
        progress_bar['value'] = 100 if es_ejecucion_exitosa else 0

def update_progress_status(message, step_value):
    if label_estado_progreso and progress_bar and ventana:
        ventana.after(0, label_estado_progreso.config, {'text': f"Estado: {message}"})
        ventana.after(0, progress_bar.config, {'value': step_value})
        ventana.after(0, ventana.update_idletasks)

def reiniciar_campos_gui():
    global RUTA_FASTQ_LECTURA1, RUTA_FASTQ_LECTURA2
    global entrada_nombre_analisis, label_fastq1_seleccionado, label_fastq2_seleccionado
    global label_estado_progreso, progress_bar, output_text
    global entrada_id_paciente, entrada_medico_solicitante, entrada_laboratorio

    if entrada_nombre_analisis:
        entrada_nombre_analisis.delete(0, tk.END)
        entrada_nombre_analisis.insert(0, generar_nombre_analisis_por_defecto())
    if entrada_id_paciente: entrada_id_paciente.delete(0, tk.END)
    if entrada_medico_solicitante: entrada_medico_solicitante.delete(0, tk.END) # Corregido
    if entrada_laboratorio: entrada_laboratorio.delete(0, tk.END)
    if label_fastq1_seleccionado:
        label_fastq1_seleccionado.config(text="Lectura 1: Ningún archivo seleccionado")
    if label_fastq2_seleccionado:
        label_fastq2_seleccionado.config(text="Lectura 2: Ningún archivo seleccionado")
    RUTA_FASTQ_LECTURA1 = ""
    RUTA_FASTQ_LECTURA2 = ""
    if label_estado_progreso:
        label_estado_progreso.config(text="Estado: Listo para iniciar")
    if progress_bar:
        progress_bar['value'] = 0
    if output_text:
        output_text.config(state=tk.NORMAL)
        output_text.delete(1.0, tk.END)
        output_text.config(state=tk.DISABLED)

def _run_wsl_command_thread():
    global RUTA_WSL_DIR_TRABAJO_ACTUAL, RUTA_WSL_FASTQ_LECTURA1, RUTA_WSL_FASTQ_LECTURA2
    global RUTA_WSL_ARCHIVO_BAM_PIPELINE, RUTA_WSL_ARCHIVO_VCF_PIPELINE

    full_output = ""
    ejecucion_exitosa = False
    tiempo_inicio_pipeline = datetime.datetime.now()

    nombre_analisis_input = entrada_nombre_analisis.get().strip()
    if not nombre_analisis_input:
        nombre_analisis_input = generar_nombre_analisis_por_defecto()
        full_output += f"Advertencia: No se ingresó un nombre de análisis. Usando '{nombre_analisis_input}' por defecto.\n"

    RUTA_WSL_DIR_TRABAJO_ACTUAL = os.path.join(RUTA_BASE_ANALISIS_WSL, nombre_analisis_input).replace("\\", "/")
    RUTA_WSL_FASTQ_LECTURA1 = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, os.path.basename(RUTA_FASTQ_LECTURA1)).replace("\\", "/")
    RUTA_WSL_FASTQ_LECTURA2 = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, os.path.basename(RUTA_FASTQ_LECTURA2)).replace("\\", "/")

    NOMBRE_ARCHIVO_VCF_PIPELINE = f"{nombre_analisis_input}.chr7.raw_variants.vcf.gz" # Usado para HaplotypeCaller output
    # NOMBRE_ARCHIVO_BAM_PIPELINE es f"{nombre_analisis_input}.bam", pero RUTA_WSL_ARCHIVO_BAM_PIPELINE se asigna a RUTA_WSL_BAM_RG

    # RUTA_WSL_ARCHIVO_VCF_PIPELINE se actualiza después de filtración para apuntar al VCF filtrado final.
    # Inicialmente apunta a la salida de HaplotypeCaller.
    ruta_vcf_haplotypecaller = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "vcf", NOMBRE_ARCHIVO_VCF_PIPELINE).replace("\\", "/")
    RUTA_WSL_ARCHIVO_VCF_PIPELINE = ruta_vcf_haplotypecaller # Asignación inicial

    RUTA_WSL_BAM_RG_NAME = f"{nombre_analisis_input}_rg.bam" # Nombre base del BAM final del pipeline
    RUTA_WSL_ARCHIVO_BAM_PIPELINE = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam", RUTA_WSL_BAM_RG_NAME).replace("\\", "/")

    try:
        update_progress_status("Iniciando proceso...", 0)
        full_output += f"Creando directorio de trabajo en WSL: {RUTA_WSL_DIR_TRABAJO_ACTUAL}\n"
        subprocess.run(['wsl.exe', 'mkdir', '-p', RUTA_WSL_DIR_TRABAJO_ACTUAL], check=True, capture_output=True, text=True, encoding='utf-8')
        path_bam_wsl = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam").replace("\\","/")
        subprocess.run(['wsl.exe', 'mkdir', '-p', path_bam_wsl], check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Creado subdirectorio BAM en WSL: {path_bam_wsl}\n"
        path_vcf_wsl = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "vcf").replace("\\","/")
        subprocess.run(['wsl.exe', 'mkdir', '-p', path_vcf_wsl], check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Creado subdirectorio VCF en WSL: {path_vcf_wsl}\n"

        update_progress_status("Copiando archivos FASTQ a WSL...", 10)
        full_output += "\nCopiando archivos FASTQ a WSL...\n"
        subprocess.run(['wsl.exe', 'cp', RUTA_FASTQ_LECTURA1.replace("\\", "/").replace("C:", "/mnt/c"), RUTA_WSL_FASTQ_LECTURA1], check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Copiado '{os.path.basename(RUTA_FASTQ_LECTURA1)}' a WSL: {RUTA_WSL_FASTQ_LECTURA1}\n"
        subprocess.run(['wsl.exe', 'cp', RUTA_FASTQ_LECTURA2.replace("\\", "/").replace("C:", "/mnt/c"), RUTA_WSL_FASTQ_LECTURA2], check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Copiado '{os.path.basename(RUTA_FASTQ_LECTURA2)}' a WSL: {RUTA_WSL_FASTQ_LECTURA2}\n"

        full_output += "\n--- Iniciando Pipeline de Análisis de Variantes en WSL ---\n"

        RUTA_WSL_BAM_ALIGN_UNSORTED = os.path.join(path_bam_wsl, f"{nombre_analisis_input}_aligned.bam").replace("\\", "/")
        RUTA_WSL_BAM_ALIGNED_SORTED = os.path.join(path_bam_wsl, f"{nombre_analisis_input}_sorted.bam").replace("\\", "/")
        RUTA_WSL_BAM_MD = os.path.join(path_bam_wsl, f"{nombre_analisis_input}_md.bam").replace("\\", "/")
        RUTA_WSL_BAM_RG = RUTA_WSL_ARCHIVO_BAM_PIPELINE # Ya tiene el path completo incluyendo /bam/

        # Paso 3.1
        update_progress_status("Ejecutando Alineamiento (BWA mem)...", 20)
        full_output += "\n[Paso 3.1/7] Alineamiento (BWA mem)...\n"
        comando_alineamiento = ['wsl.exe', 'bash', '-c', f"bwa mem -t 20 {RUTA_GENOMA_REFERENCIA_WSL} {RUTA_WSL_FASTQ_LECTURA1} {RUTA_WSL_FASTQ_LECTURA2} | samtools view -Sb - > {RUTA_WSL_BAM_ALIGN_UNSORTED}"]
        subprocess.run(comando_alineamiento, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += "Alineamiento completado.\n"

        # Paso 3.2
        update_progress_status("Ordenando BAM (samtools sort)...", 30)
        full_output += "\n[Paso 3.2/7] Ordenar BAM (samtools sort)...\n"
        comando_sort_bam = ['wsl.exe', 'samtools', 'sort', '-o', RUTA_WSL_BAM_ALIGNED_SORTED, RUTA_WSL_BAM_ALIGN_UNSORTED]
        subprocess.run(comando_sort_bam, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += "Ordenar BAM completado.\n"

        # Paso 3.3
        update_progress_status("Marcando duplicados (GATK MarkDuplicates)...", 45)
        full_output += "\n[Paso 3.3/7] Marcar duplicados (GATK MarkDuplicates)...\n"
        RUTA_WSL_METRICAS_DEDUP = os.path.join(path_bam_wsl, f"{nombre_analisis_input}.dedup_metrics.txt").replace("\\", "/")
        comando_markduplicates = ['wsl.exe', 'gatk', 'MarkDuplicates', '-I', RUTA_WSL_BAM_ALIGNED_SORTED, '-O', RUTA_WSL_BAM_MD, '-M', RUTA_WSL_METRICAS_DEDUP]
        subprocess.run(comando_markduplicates, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += "Marcado de duplicados completado.\n"

        # Paso 3.4
        update_progress_status("Añadiendo grupos de lectura (samtools addreplacerg)...", 60)
        full_output += "\n[Paso 3.4/7] Añadir grupos de lectura (samtools addreplacerg)...\n"
        read_group_header = f"@RG\tID:rg1\tSM:{nombre_analisis_input}\tLB:lib1\tPL:ILLUMINA"
        comando_add_rg = ['wsl.exe', 'samtools', 'addreplacerg', '-r', read_group_header, RUTA_WSL_BAM_MD, '-o', RUTA_WSL_BAM_RG]
        subprocess.run(comando_add_rg, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += "Añadir grupos de lectura completado.\n"

        # Paso 3.5
        update_progress_status("Indexando BAM (samtools index)...", 70)
        full_output += "\n[Paso 3.5/7] Indexar BAM (samtools index)...\n"
        comando_index_bam = ['wsl.exe', 'samtools', 'index', RUTA_WSL_BAM_RG]
        subprocess.run(comando_index_bam, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += "Indexación de BAM completada.\n"

        # Paso 3.6
        update_progress_status("Llamada de variantes (GATK HaplotypeCaller - chr7)...", 80)
        full_output += "\n[Paso 3.6/7] Llamada de variantes (GATK HaplotypeCaller - chr7)...\n"
        comando_haplotypecaller = ['wsl.exe', 'gatk', 'HaplotypeCaller', '-R', RUTA_GENOMA_REFERENCIA_WSL, '-I', RUTA_WSL_BAM_RG, '-O', RUTA_WSL_ARCHIVO_VCF_PIPELINE, '-L', 'chr7']
        subprocess.run(comando_haplotypecaller, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += "Llamada de variantes completada.\n"

        # Paso 3.7
        update_progress_status("Anotación y Filtrado de Variantes...", 90)
        RUTA_WSL_VCF_ANOTADO = os.path.join(path_vcf_wsl, f"{nombre_analisis_input}.chr7.annotated.vcf.gz").replace("\\", "/")
        full_output += "\n[Paso 3.7a/7] Anotación de Variantes (GATK VariantAnnotator)...\n"
        comando_variant_annotator = ['wsl.exe', 'gatk', 'VariantAnnotator', '-R', RUTA_GENOMA_REFERENCIA_WSL, '-V', RUTA_WSL_ARCHIVO_VCF_PIPELINE, '-A', 'QualByDepth', '-A', 'FisherStrand', '-A', 'StrandOddsRatio', '-A', 'RMSMappingQuality', '-A', 'MappingQualityRankSumTest', '-A', 'ReadPosRankSumTest', '-O', RUTA_WSL_VCF_ANOTADO]
        annotator_result = subprocess.run(comando_variant_annotator, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Salida de VariantAnnotator:\n{annotator_result.stdout.strip()}\n"
        if annotator_result.stderr: full_output += f"Errores/Advertencias de VariantAnnotator:\n{annotator_result.stderr.strip()}\n"
        full_output += "Anotación de variantes completada.\n"

        RUTA_WSL_VCF_FILTRADO = os.path.join(path_vcf_wsl, f"{nombre_analisis_input}.chr7.filtered.vcf.gz").replace("\\", "/")
        full_output += "\n[Paso 3.7b/7] Filtrado de Variantes (GATK VariantFiltration)...\n"
        comando_variant_filtration = ['wsl.exe', 'gatk', 'VariantFiltration', '-V', RUTA_WSL_VCF_ANOTADO, '-filter', "QD < 2.0", '--filter-name', "LowQD", '-filter', "FS > 60.0", '--filter-name', "StrandBiasFS", '-filter', "SOR > 3.0", '--filter-name', "StrandBiasSOR", '-filter', "MQ < 40.0", '--filter-name', "LowMQ", '-filter', "MQRankSum < -12.5", '--filter-name', "MQRankSum", '-filter', "ReadPosRankSum < -8.0", '--filter-name', "ReadPosRankSum", '-O', RUTA_WSL_VCF_FILTRADO]
        filtration_result = subprocess.run(comando_variant_filtration, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Salida de VariantFiltration:\n{filtration_result.stdout.strip()}\n"
        if filtration_result.stderr: full_output += f"Errores/Advertencias de VariantFiltration:\n{filtration_result.stderr.strip()}\n"
        full_output += "Filtrado de variantes completado.\n"

        RUTA_WSL_ARCHIVO_VCF_PIPELINE = RUTA_WSL_VCF_FILTRADO
        full_output += f"El archivo VCF final para copiar es ahora: {RUTA_WSL_ARCHIVO_VCF_PIPELINE}\n"
        full_output += "Paso de Anotación y Filtrado completado.\n"
        full_output += "\n--- Pipeline completado en WSL ---\n"

        comando_ls_wsl_output = ['wsl.exe', 'ls', '-l', RUTA_WSL_DIR_TRABAJO_ACTUAL]
        ls_output_result = subprocess.run(comando_ls_wsl_output, capture_output=True, text=True, check=False, encoding='utf-8')
        full_output += f"Listado de '{RUTA_WSL_DIR_TRABAJO_ACTUAL}' en WSL:\n{ls_output_result.stdout.strip()}\n\n"

        update_progress_status("Copiando resultados finales...", 95)
        dir_origen_fastqs = os.path.dirname(RUTA_FASTQ_LECTURA1)
        carpeta_bam_origen = os.path.join(dir_origen_fastqs, "bam")
        os.makedirs(carpeta_bam_origen, exist_ok=True)
        full_output += f"Carpeta de destino BAM (Windows) creada/existente en: {carpeta_bam_origen}\n"
        path_wsl_bam_source_folder = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "bam", ".").replace("\\", "/")
        path_windows_bam_dest_folder_converted = convertir_ruta_windows_a_wsl(carpeta_bam_origen)
        comando_copia_bam_folder = ['wsl.exe', 'cp', '-r', path_wsl_bam_source_folder, path_windows_bam_dest_folder_converted]
        subprocess.run(comando_copia_bam_folder, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Contenido de la carpeta BAM copiado a: {carpeta_bam_origen}\n"

        carpeta_vcf_origen = os.path.join(dir_origen_fastqs, "vcf")
        os.makedirs(carpeta_vcf_origen, exist_ok=True)
        full_output += f"Carpeta de destino VCF (Windows) creada/existente en: {carpeta_vcf_origen}\n"
        path_wsl_vcf_source_folder = os.path.join(RUTA_WSL_DIR_TRABAJO_ACTUAL, "vcf", ".").replace("\\", "/")
        path_windows_vcf_dest_folder_converted = convertir_ruta_windows_a_wsl(carpeta_vcf_origen)
        comando_copia_vcf_folder = ['wsl.exe', 'cp', '-r', path_wsl_vcf_source_folder, path_windows_vcf_dest_folder_converted]
        subprocess.run(comando_copia_vcf_folder, check=True, capture_output=True, text=True, encoding='utf-8')
        full_output += f"Contenido de la carpeta VCF copiado a: {carpeta_vcf_origen}\n"

        # --- Indexar VCF final en Windows usando Tabix vía WSL ---
        update_progress_status("Indexando archivo VCF final con Tabix...", 97)
        full_output += "\nIndexando VCF final con Tabix...\n"
        # NOMBRE_ARCHIVO_VCF_PIPELINE ya tiene el nombre del VCF filtrado.
        # PERO RUTA_WSL_ARCHIVO_VCF_PIPELINE es el path en WSL. Necesitamos el nombre base para construir el path en Windows.
        nombre_base_vcf_filtrado = os.path.basename(RUTA_WSL_ARCHIVO_VCF_PIPELINE) # Esto dará el nombre de archivo correcto
        ruta_vcf_windows_final = os.path.join(carpeta_vcf_origen, nombre_base_vcf_filtrado) # Path correcto en Windows

        if os.path.exists(ruta_vcf_windows_final):
            ruta_vcf_para_wsl_tabix = convertir_ruta_windows_a_wsl(ruta_vcf_windows_final)
            comando_tabix = ['wsl.exe', 'tabix', '-f', '-p', 'vcf', ruta_vcf_para_wsl_tabix]
            try:
                tabix_result = subprocess.run(comando_tabix, check=True, capture_output=True, text=True, encoding='utf-8')
                full_output += f"Salida de Tabix:\n{tabix_result.stdout.strip()}\n"
                if tabix_result.stderr: full_output += f"Errores/Advertencias de Tabix:\n{tabix_result.stderr.strip()}\n"
                full_output += f"Indexación con Tabix completada para: {ruta_vcf_windows_final}\n"
            except subprocess.CalledProcessError as e_tabix:
                full_output += f"\nERROR al indexar con Tabix (código: {e_tabix.returncode}):\n{e_tabix.stderr.strip()}\n"
                full_output += f"Comando Tabix fallido: {' '.join(e_tabix.cmd)}\n"
        else:
            full_output += f"\nADVERTENCIA: No se encontró el archivo VCF final en Windows para indexar con Tabix: {ruta_vcf_windows_final}\n"
        # --- Fin Indexar VCF ---

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
        full_output += f"\nERROR AL EJECUTAR COMANDO WSL (código: {e.returncode}):\n{e.stderr.strip()}\n"
        full_output += f"Comando fallido: {' '.join(e.cmd)}\n"
        update_progress_status("Proceso fallido.", 0)
    except FileNotFoundError:
        full_output = "Error: 'wsl.exe' no encontrado..."
        update_progress_status("Error: WSL no encontrado.", 0)
    except Exception as e:
        full_output += f"\nOCURRIÓ UN ERROR INESPERADO EN PYTHON: {e}"
        update_progress_status("Proceso fallido (error inesperado).", 0)
    finally:
        if ventana:
            ventana.after(0, update_gui_with_result, full_output, ejecucion_exitosa)
        else:
            print(full_output)

def main():
    global ventana, boton_ejecutar_wsl, output_text, label_fastq1_seleccionado, label_fastq2_seleccionado, entrada_nombre_analisis, label_estado_progreso, progress_bar
    global entrada_id_paciente, entrada_medico_solicitante, entrada_laboratorio # Corregido: entrada_medico_solicitante

    ventana = tk.Tk()
    ventana.title("Análisis de Variantes en CFTR")
    ventana.geometry("950x850")
    ventana.resizable(True, True)

    menubar = tk.Menu(ventana)
    archivo_menu = tk.Menu(menubar, tearoff=0)
    archivo_menu.add_command(label="Salir", command=ventana.destroy)
    menubar.add_cascade(label="Archivo", menu=archivo_menu)
    ayuda_menu = tk.Menu(menubar, tearoff=0)
    creditos_completos = ("Análisis de Variantes en CFTR\n\nVersión 1.1.1\n\n© 2025 GBSCorelab. Todos los derechos reservados.\nDesarrollador: Germán Peña\ngermanpet@gmail.com (Soporte y Café)")
    ayuda_menu.add_command(label="Acerca de...", command=lambda: messagebox.showinfo("Acerca de Análisis de Variantes en CFTR", creditos_completos))
    instrucciones_texto = ("1. Ingresa un nombre para el análisis o usa el sugerido del FASTQ R1.\n2. Selecciona los archivos de Lectura FASTQ (R1 y R2).\n3. Ingresa los datos para el informe (opcional).\n4. Haz clic en 'Iniciar Análisis' para ejecutar el pipeline.\n5. Los resultados (carpetas 'bam', 'vcf' y reportes) se guardarán junto a tus archivos FASTQ de origen.\n6. Usa 'Reiniciar GUI' para limpiar los campos para un nuevo análisis.") # Actualizadas instrucciones
    ayuda_menu.add_command(label="Instrucciones", command=lambda: messagebox.showinfo("Instrucciones de Uso", instrucciones_texto))
    menubar.add_cascade(label="Ayuda", menu=ayuda_menu)
    ventana.config(menu=menubar)

    frame = ttk.Frame(ventana, padding="15")
    frame.pack(fill='both', expand=True)

    label_nombre_analisis_instruccion = ttk.Label(frame, text="1. Ingresa un nombre para este análisis (opcional, se sugiere del FASTQ R1):", font=('Helvetica', 11))
    label_nombre_analisis_instruccion.pack(pady=5, anchor='w')
    entrada_nombre_analisis = ttk.Entry(frame, width=50)
    entrada_nombre_analisis.pack(pady=5, anchor='w')
    entrada_nombre_analisis.insert(0, generar_nombre_analisis_por_defecto())
    ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=10)

    label_fastq_instruccion = ttk.Label(frame, text="2. Selecciona tus archivos de Lectura FASTQ:", font=('Helvetica', 11))
    label_fastq_instruccion.pack(pady=5, anchor='w')
    # ... (resto de la GUI como estaba, incluyendo la SECCIÓN DE DATOS DEL INFORME y la SECCIÓN WORKFLOW simplificada) ...
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

    # --- Sección Datos del Informe ---
    label_datos_informe_titulo = ttk.Label(frame, text="2b. Datos para el Informe (Opcional):", font=('Helvetica', 11))
    label_datos_informe_titulo.pack(pady=(10,5), anchor='w')
    frame_id_paciente = ttk.Frame(frame)
    frame_id_paciente.pack(fill='x', padx=5, pady=2)
    label_id_paciente = ttk.Label(frame_id_paciente, text="ID Paciente:", width=20, anchor='w')
    label_id_paciente.pack(side='left')
    entrada_id_paciente = ttk.Entry(frame_id_paciente, width=50)
    entrada_id_paciente.pack(side='left', expand=True, fill='x')
    frame_medico = ttk.Frame(frame)
    frame_medico.pack(fill='x', pady=2)
    label_medico = ttk.Label(frame_medico, text="Médico Solicitante:", width=20)
    label_medico.pack(side='left', padx=(0,5))
    entrada_medico_solicitante = ttk.Entry(frame_medico, width=50) # Corregido aquí
    entrada_medico_solicitante.pack(side='left', fill='x', expand=True)
    frame_laboratorio = ttk.Frame(frame)
    frame_laboratorio.pack(fill='x', pady=2)
    label_laboratorio = ttk.Label(frame_laboratorio, text="Laboratorio:", width=20)
    label_laboratorio.pack(side='left', padx=(0,5))
    entrada_laboratorio = ttk.Entry(frame_laboratorio, width=50)
    entrada_laboratorio.pack(side='left', fill='x', expand=True)
    ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=10)
    # --- Fin Sección Datos del Informe ---

    label_workflow_titulo = ttk.Label(frame, text="3. Workflow de Análisis de Variantes en WSL:", font=('Helvetica', 11, 'bold'))
    label_workflow_titulo.pack(pady=5, anchor='w')
    label_info_origen = ttk.Label(frame, text="**NOTA:** Los resultados (bam, vcf, reportes) se guardarán en subcarpetas junto a tus FASTQ de origen.", font=('Helvetica', 9), foreground='blue', wraplength=850) # Actualizado
    label_info_origen.pack(pady=10, anchor='w')
    ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=10)

    label_ejecucion_instruccion = ttk.Label(frame, text="4. Ejecuta el pipeline y genera reportes:", font=('Helvetica', 11)) # Actualizado
    label_ejecucion_instruccion.pack(pady=5, anchor='w')
    boton_ejecutar_wsl = ttk.Button(frame, text="Iniciar Análisis y Reportes", command=ejecutar_comando_wsl) # Actualizado
    boton_ejecutar_wsl.pack(pady=10)
    boton_reiniciar_gui = ttk.Button(frame, text="Reiniciar GUI", command=reiniciar_campos_gui)
    boton_reiniciar_gui.pack(pady=5)
    label_estado_progreso = ttk.Label(frame, text="Estado: Listo para iniciar", font=('Helvetica', 10, 'italic'))
    label_estado_progreso.pack(pady=5, anchor='w')
    progress_bar = ttk.Progressbar(frame, orient='horizontal', length=800, mode='determinate')
    progress_bar.pack(pady=5)
    output_text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, width=90, height=15, font=('Courier New', 10), background='black', foreground='lightgreen', state=tk.DISABLED)
    output_text.pack(pady=10, fill='both', expand=True)

    nombre_usuario = obtener_usuario_wsl()
    if nombre_usuario is None:
        messagebox.showerror("Error de Configuración WSL", "No se pudo determinar el nombre de usuario...")
        if boton_ejecutar_wsl: boton_ejecutar_wsl.config(state=tk.DISABLED)
    else:
        global USUARIO_WSL_ACTUAL, RUTA_BASE_ANALISIS_WSL, RUTA_GENOMA_REFERENCIA_WSL
        USUARIO_WSL_ACTUAL = nombre_usuario
        RUTA_BASE_ANALISIS_WSL = f"/home/{USUARIO_WSL_ACTUAL}/analisis/" # Mantener /analisis/ como en la última versión funcional
        RUTA_GENOMA_REFERENCIA_WSL = f"/home/{USUARIO_WSL_ACTUAL}/analisis/reference/GRCh38.fa" # Mantener /analisis/ como en la última versión funcional
        if boton_ejecutar_wsl: boton_ejecutar_wsl.config(state=tk.NORMAL)
        print(f"Usuario WSL detectado: {USUARIO_WSL_ACTUAL}")
        print(f"Ruta base de análisis WSL actualizada: {RUTA_BASE_ANALISIS_WSL}")
        print(f"Ruta genoma de referencia WSL actualizada: {RUTA_GENOMA_REFERENCIA_WSL}")

    progress_bar['value'] = 0
    ventana.mainloop()

if __name__ == "__main__":
    main()

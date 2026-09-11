<#
.SYNOPSIS
    Convierte entre Office y PDF usando el Office instalado, en los dos sentidos.

.DESCRIPTION
    Lo lanza `apps/documents/office.py`, **siempre como proceso hijo**. Esa no es una
    comodidad: Word se cuelga de verdad -- un documento con una macro, un vinculo a una
    plantilla que ya no esta, un panel de recuperacion -- y si se colgara dentro de Django se
    llevaria el servidor por delante. Aqui, como mucho, se mata el hijo.

    Y por eso no hay ninguna dependencia de Python nueva: PowerShell ya habla COM, y usarlo
    da el aislamiento de regalo.

.NOTES
    Las tres aplicaciones se parecen y **no se comportan igual**, que es donde esto falla si
    se escribe de memoria:

      - Word exporta con ExportAsFixedFormat($ruta, 17).
      - Excel invierte los argumentos: ExportAsFixedFormat(0, $ruta). Primero el tipo.
      - PowerPoint ignora Visible = $false; hay que abrir con WithWindow = $false o se ve
        la ventana aparecer en la cara de quien esta usando el equipo.

    Y las tres tienen que cerrarse en `finally`. Un WINWORD.EXE huerfano se queda con el
    archivo bloqueado y el siguiente intento falla sin decir por que.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Origen,
    [Parameter(Mandatory = $true)][string]$Destino,
    # word | excel | powerpoint | pdf-a-word
    [Parameter(Mandatory = $true)][string]$Programa,
    # Solo para Excel: encajar cada hoja a lo ancho de una pagina.
    [switch]$AjustarAncho
)

$ErrorActionPreference = 'Stop'

# Rutas absolutas siempre: Office resuelve una ruta relativa contra **su** directorio de
# trabajo, no contra el nuestro, y el sintoma es «no se encuentra el archivo» sobre un
# archivo que esta ahi delante.
$Origen = [System.IO.Path]::GetFullPath($Origen)
$Destino = [System.IO.Path]::GetFullPath($Destino)

if (-not (Test-Path -LiteralPath $Origen)) {
    Write-Error "No existe $Origen"
    exit 2
}

$app = $null
$documento = $null

try {
    switch ($Programa) {
        'word' {
            $app = New-Object -ComObject Word.Application
            $app.Visible = $false
            $app.DisplayAlerts = 0
            # msoAutomationSecurityForceDisable: un .docm que llega por correo no ejecuta
            # nada al abrirse. Sin esto, convertir un documento es ejecutarlo.
            $app.AutomationSecurity = 3

            $documento = $app.Documents.Open(
                $Origen,
                [ref]$false,   # ConfirmConversions
                [ref]$true,    # ReadOnly
                [ref]$false    # AddToRecentFiles -- no ensuciamos su lista de recientes
            )
            # wdExportFormatPDF = 17. ExportAsFixedFormat y no SaveAs: conserva el indice,
            # los marcadores y los enlaces, que es la diferencia entre un PDF util y una
            # foto del documento.
            $documento.ExportAsFixedFormat($Destino, 17)
            $documento.Close(0)   # wdDoNotSaveChanges
            $documento = $null
        }

        'excel' {
            $app = New-Object -ComObject Excel.Application
            $app.Visible = $false
            $app.DisplayAlerts = $false
            $app.AutomationSecurity = 3

            $documento = $app.Workbooks.Open(
                $Origen,
                0,      # UpdateLinks: 0 = no actualizar. Un vinculo a un libro en un disco
                        # de red que ya no existe deja Excel esperando hasta que caduca.
                $true   # ReadOnly
            )

            if ($AjustarAncho) {
                # Una hoja de calculo **no tiene tamano de pagina**. Sin esto, un libro ancho
                # sale en cuarenta paginas de tres columnas cada una, que es inservible.
                foreach ($hoja in $documento.Worksheets) {
                    $hoja.PageSetup.Zoom = $false
                    $hoja.PageSetup.FitToPagesWide = 1
                    $hoja.PageSetup.FitToPagesTall = $false
                }
            }

            # xlTypePDF = 0. Ojo al orden: aqui el tipo va **primero**, al reves que en Word.
            $documento.ExportAsFixedFormat(0, $Destino)
            $documento.Close($false)
            $documento = $null
        }

        'powerpoint' {
            $app = New-Object -ComObject PowerPoint.Application
            $app.DisplayAlerts = 1   # ppAlertsNone

            $documento = $app.Presentations.Open(
                $Origen,
                $true,    # ReadOnly
                $false,   # Untitled
                $false    # WithWindow -- PowerPoint no admite Visible = $false; es aqui
                          # donde se le dice que no abra ventana.
            )
            # ppSaveAsPDF = 32, con SaveAs y **no** con ExportAsFixedFormat.
            #
            # No es una preferencia: ExportAsFixedFormat de PowerPoint tiene dieciseis
            # parametros opcionales y el enlace tardio de PowerShell no consigue pasarle el
            # enum -- responde «no se puede convertir el valor 2 de tipo int al tipo Object».
            # SaveAs tiene una firma simple y hace lo mismo. El .pptx original no se toca:
            # se guarda una copia en la ruta nueva y se cierra sin guardar.
            $documento.SaveAs($Destino, 32)
            $documento.Close()
            $documento = $null
        }

        'pdf-a-word' {
            # El camino de vuelta, y lo hace **Word**, no nosotros.
            #
            # Word 2013 y posteriores convierten un PDF al abrirlo -- lo llaman PDF Reflow --
            # reconstruyendo parrafos, tablas y estilos a partir de las posiciones de las
            # letras. Es lo mejor que hay: la alternativa de Python es pdf2docx, que por
            # dentro es PyMuPDF, **AGPL-3**, y esa puerta ya se cerro dos veces en este
            # proyecto.
            $app = New-Object -ComObject Word.Application
            $app.Visible = $false
            # Sin esto, Word para a preguntar «voy a convertir tu PDF en un documento
            # editable, ¿sigo?» y el proceso se queda esperando una respuesta que no va a
            # llegar nunca.
            $app.DisplayAlerts = 0
            $app.AutomationSecurity = 3

            # **Sin ReadOnly**, al reves que en los demas: aqui abrir es convertir, y un
            # documento de solo lectura no se puede convertir.
            $documento = $app.Documents.Open(
                $Origen,
                [ref]$false,   # ConfirmConversions
                [ref]$false,   # ReadOnly
                [ref]$false    # AddToRecentFiles
            )
            # wdFormatXMLDocument = 12, que es .docx
            $documento.SaveAs2($Destino, 12)
            $documento.Close(0)
            $documento = $null
        }

        default {
            Write-Error "Programa desconocido: $Programa"
            exit 2
        }
    }
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
finally {
    # Cerrar pase lo que pase. Un proceso de Office huerfano se queda con el archivo
    # bloqueado y el intento siguiente falla sin decir por que.
    if ($null -ne $documento) {
        try { $documento.Close() } catch { }
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($documento)
    }
    if ($null -ne $app) {
        try { $app.Quit() } catch { }
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
    }
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}

# **No se cree el codigo de salida.** Es la regla escrita en AGENTS.md y aqui aplica igual:
# Office devuelve 0 despues de no escribir nada mas veces de las que parece.
if (-not (Test-Path -LiteralPath $Destino)) {
    Write-Error "Office dijo que si, pero no hay ningun archivo en $Destino"
    exit 3
}

exit 0

"""Facturas LH - Listados de facturas para Ferretería LH S.L."""
import os
import sys


def _autoprueba() -> bool:
    """Prueba de actualización usada por GitHub antes de publicar cada versión.

    FacturasLH.exe --autoprueba NUEVO.exe MARCA  -> se sustituye a sí mismo y se reinicia
    FacturasLH.exe --autoprueba-fin MARCA        -> el reinicio funcionó: escribe OK
    """
    if len(sys.argv) >= 3 and sys.argv[1] == "--autoprueba-fin":
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write("OK")
        return True
    if len(sys.argv) >= 4 and sys.argv[1] == "--autoprueba":
        from pathlib import Path
        from app.actualizador import lanzar_sustitucion
        lanzar_sustitucion(os.getpid(), Path(sys.argv[2]), Path(sys.executable),
                           argumentos=f'--autoprueba-fin "{sys.argv[3]}"')
        os._exit(0)
    return False


if __name__ == "__main__":
    if not _autoprueba():
        from app.interfaz import iniciar
        iniciar()

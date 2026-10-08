# Facturas LH

Programa de Windows para **Ferretería LH S.L.** que convierte el diario de facturación en
listados de facturas por cliente, con el logo y los datos de la empresa, listos para ver,
imprimir o enviar por email.

## Qué hace

1. **Recibe el diario solo.** Cada pocos minutos revisa la carpeta *Diarios* del correo
   `contabilidad@ferreterialashuertas.es` y descarga el diario (PDF, Excel o CSV).
2. **Lee todas las facturas** y las separa por cliente: tipo (Contado, Crédito, Simplificada,
   Rectificativa), número, fecha, base imponible, % y cuota de IVA, recargo de equivalencia,
   retención de IRPF y total. Si una factura no cuadra (base + impuestos ≠ total) la marca en naranja.
3. **Genera un PDF por cliente** titulado *Listado de facturas*, con nuestros datos, los del
   cliente, todas sus facturas, el resumen por tipo de IVA y los totales.
4. Desde el programa puedes **verlo, imprimirlo, enviarlo por email** al cliente (o a quien
   quieras) y exportarlo a **Excel o CSV** si el cliente lo pide. También *Enviar a todos*.
5. **Modelo 347:** lista los clientes con operaciones anuales superiores a 3.005,06 € (IVA
   incluido) y genera la carta de confirmación (con el destinatario en la ventana del sobre),
   para ver, imprimir o enviar por email.
6. **Se actualiza solo** desde el repositorio kikoalvarezg99-star/FacturasLH de GitHub.

## Primera instalación en el PC de la tienda

1. Ve a la página **Releases** del repositorio kikoalvarezg99-star/FacturasLH y descarga `FacturasLH.exe`.
2. Crea la carpeta `C:\Users\<tu usuario>\FacturasLH` (o en Documentos) y guarda ahí el `.exe`.
   No lo pongas en *Archivos de programa*, porque ahí no se puede actualizar solo.
3. Ábrelo. Si Windows muestra «Windows protegió su PC», pulsa *Más información → Ejecutar de todas formas*
   (pasa con los programas nuevos que no están firmados; solo la primera vez).
4. Botón derecho en el `.exe` → *Anclar a la barra de tareas*.

## Configuración (una sola vez)

En **Configuración** (protegida con código de acceso):

- **Datos de la empresa:** son fijos (Ferretería LH S.L., B90430356) y no se pueden cambiar.
- **Correo:** usuario, contraseña, servidor IMAP y SMTP. Los da tu proveedor de correo
  (normalmente `mail.ferreterialashuertas.es`, IMAP 993 y SMTP 465 con SSL). Pulsa
  **Probar conexión**.
- **Carpeta de diarios:** `Diarios`. En el correo crea esa carpeta y una regla para que los
  correos con el diario se muevan ahí automáticamente.
- Marca **Abrir el programa al iniciar Windows** para que esté siempre revisando el correo.

En **Clientes → Importar clientes (CSV / Excel)** carga la ficha de clientes exportada del
programa de gestión: así cada listado lleva el NIF, la dirección y el email del cliente.
Se puede repetir cuando haya clientes nuevos (actualiza sin duplicar). Al enviar un email
también puedes guardar la dirección en la ficha.

## Elegir el periodo

El diario puede abarcar todo el año. En la pantalla *Diarios* escribe las fechas *desde / hasta*
o pulsa **Mes anterior**, **Este mes** o **Todo**: la lista de clientes, los PDF y los emails
se ajustan a ese periodo.

## Publicar una actualización

1. Sube los cambios del código a este repositorio.
2. Pestaña **Actions → Publicar versión → Run workflow**.
3. Escribe el número de versión nuevo (p. ej. `1.0.1`) y qué cambia. Pulsa *Run workflow*.
4. En unos 4 minutos GitHub crea `FacturasLH.exe` en *Releases*. Los programas instalados
   avisan al abrirse («Nueva versión disponible») y se actualizan con un clic.

## Formatos de diario admitidos

El lector no depende de un programa de gestión concreto. Busca la fila de cabecera
(Nº factura, Fecha, Cliente, NIF, Base, % IVA, Cuota IVA, R.E., IRPF, Total, Forma de pago…)
y reconoce:

- Diarios con una fila por factura y el cliente en una columna.
- El *Diario de facturación ampliado* (Tipo, Código, Fecha, Vencim., Cliente, Base, PVP…):
  el IVA se calcula a partir de Base y PVP y detecta el recargo de equivalencia.
- Diarios agrupados por cliente (`Cliente: 4300101 NOMBRE … NIF …`) con subtotales.
- Facturas con varios tipos de IVA en líneas consecutivas.
- PDF, Excel (.xlsx) y CSV.

Si el tipo de factura no aparece en el diario, se deduce por la serie (por ejemplo `FS` =
Simplificada, `R` = Rectificativa). Las reglas se cambian en *Configuración → Tipo de factura
según la serie*, y el tipo de cualquier factura se puede corregir con doble clic.

## Dónde se guardan las cosas

- Listados PDF / Excel: `Documentos\Facturas LH\<año-mes>\`
- Configuración, clientes y diarios procesados: `%APPDATA%\FacturasLH\`
- La contraseña del correo se guarda en el Administrador de credenciales de Windows.

## Ejecutar desde el código (desarrollo)

```bash
pip install -r requirements.txt
python main.py
```

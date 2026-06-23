* Ejecutar en consola para clonar el repositorio:

  ```
  git clone https://github.com/RaulCarrionAc/ICF.git
  ```
* Ejecutar en consola en consola para instalar uv:

  ```
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

  Una vez instalado uv y copiado el repositorio realizar

```
uv sync
```


en la raiz del repo y queda listo

para correr el script usar en consola:

```
uv run python -m main
```

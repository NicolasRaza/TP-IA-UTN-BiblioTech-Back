"""Notificaciones, auditoría, configuración y aprendizaje: contrato y permisos.

Lo que se verifica acá es sobre todo quién puede hacer qué. Son las cuatro
features que antes vivían en el navegador, donde no había permisos posibles: el
dueño de los datos era quien tuviera la pestaña abierta. Al mudarlas al
servidor, el control de acceso deja de ser un detalle y pasa a ser la mitad del
trabajo.
"""

import pytest


# ── Notificaciones ────────────────────────────────────────────────────────────

async def test_el_personal_emite_avisos_y_el_lector_los_ve(cliente, datos, base_url):
    r = await cliente.post(f"{base_url}/notificaciones", headers=datos["biblio"], json={
        "lector_id": datos["lector_id"], "tipo": "vencimiento_proximo",
        "titulo": "Vence pronto", "descripcion": "Tu préstamo vence en 3 días",
    })
    assert r.status_code == 201, r.text

    r = await cliente.get(f"{base_url}/notificaciones", headers=datos["lector"])
    assert r.status_code == 200
    assert [n["titulo"] for n in r.json()] == ["Vence pronto"]


async def test_un_lector_no_puede_emitir_avisos(cliente, datos, base_url):
    r = await cliente.post(f"{base_url}/notificaciones", headers=datos["lector"], json={
        "lector_id": datos["lector_id"], "tipo": "recomendacion",
        "titulo": "x", "descripcion": "y",
    })
    assert r.status_code == 403


async def test_un_lector_no_puede_leer_las_de_otro(cliente, datos, base_url):
    # Un 403 y no un listado vacío: el vacío se confunde con "no tenés avisos".
    r = await cliente.get(
        f"{base_url}/notificaciones", params={"lector_id": datos["otro_id"]},
        headers=datos["lector"],
    )
    assert r.status_code == 403


async def test_el_personal_tiene_que_decir_de_quien(cliente, datos, base_url):
    r = await cliente.get(f"{base_url}/notificaciones", headers=datos["biblio"])
    assert r.status_code == 422


async def test_marcar_leida_y_marcar_todas(cliente, datos, base_url):
    creada = await cliente.post(f"{base_url}/notificaciones", headers=datos["biblio"], json={
        "lector_id": datos["lector_id"], "tipo": "recomendacion",
        "titulo": "a", "descripcion": "b",
    })
    notif_id = creada.json()["id"]

    ajena = await cliente.patch(
        f"{base_url}/notificaciones/{notif_id}/leida", headers=datos["otro"])
    assert ajena.status_code == 403

    propia = await cliente.patch(
        f"{base_url}/notificaciones/{notif_id}/leida", headers=datos["lector"])
    assert propia.status_code == 200
    assert propia.json()["leida"] is True

    await cliente.post(f"{base_url}/notificaciones", headers=datos["biblio"], json={
        "lector_id": datos["lector_id"], "tipo": "recomendacion",
        "titulo": "c", "descripcion": "d",
    })
    todas = await cliente.post(
        f"{base_url}/notificaciones/marcar-leidas", headers=datos["lector"])
    assert todas.json()["marcadas"] == 1, "sólo cuenta las que estaban sin leer"


# ── Auditoría ─────────────────────────────────────────────────────────────────

async def test_el_autor_del_evento_sale_del_token(cliente, datos, base_url):
    r = await cliente.post(f"{base_url}/auditoria", headers=datos["biblio"], json={
        "tipo": "alta_libro", "descripcion": "Se dio de alta Rayuela",
    })
    assert r.status_code == 201, r.text
    assert r.json()["usuario_id"] is not None


@pytest.mark.parametrize("metodo", ["get", "post"])
async def test_la_auditoria_es_del_personal(cliente, datos, base_url, metodo):
    llamar = getattr(cliente, metodo)
    kwargs = {"headers": datos["lector"]}
    if metodo == "post":
        kwargs["json"] = {"tipo": "alta_libro", "descripcion": "no debería"}
    r = await llamar(f"{base_url}/auditoria", **kwargs)
    assert r.status_code == 403


async def test_el_autorregistro_deja_traza_sin_token(cliente, datos, base_url):
    """El alta pública no puede auditarse desde el cliente —no hay token—, así
    que la escribe el servidor dentro de la misma transacción."""
    alta = await cliente.post(f"{base_url}/lectores/", json={
        "nombre": "Nuevo", "apellido": "Lector", "documento": "41222333",
        "fecha_nacimiento": "1995-05-05", "email": "nuevo@t.com",
        "categoria": "adulto", "consentimiento_datos": True,
    })
    assert alta.status_code == 201, alta.text

    eventos = await cliente.get(
        f"{base_url}/auditoria", params={"tipo": "alta_lector"}, headers=datos["biblio"])
    assert len(eventos.json()) == 1
    assert "41222333" in eventos.json()[0]["descripcion"]


# ── Configuración ─────────────────────────────────────────────────────────────

async def test_la_configuracion_nace_con_los_valores_de_la_spec(cliente, datos, base_url):
    r = await cliente.get(f"{base_url}/configuracion", headers=datos["lector"])
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["plazo_prestamo_dias"]["docente"] == 21
    assert cfg["plazo_retiro_reserva_horas"] == 48
    assert cfg["peso_historial_recomendacion"] == 0.7


async def test_solo_el_administrador_cambia_los_parametros(cliente, datos, base_url):
    cuerpo = _cuerpo_configuracion(await _configuracion(cliente, datos, base_url))
    cuerpo["multa_por_dia_demora"] = 250

    ajeno = await cliente.put(f"{base_url}/configuracion", headers=datos["biblio"], json=cuerpo)
    assert ajeno.status_code == 403

    propio = await cliente.put(f"{base_url}/configuracion", headers=datos["admin"], json=cuerpo)
    assert propio.status_code == 200, propio.text
    assert propio.json()["multa_por_dia_demora"] == 250

    releido = await _configuracion(cliente, datos, base_url)
    assert releido["multa_por_dia_demora"] == 250, "el cambio vale para todos, no por sesión"


async def test_un_limite_en_cero_se_rechaza(cliente, datos, base_url):
    # Dejaría a esa categoría sin poder operar, y el error aparecería recién en
    # el mostrador como un préstamo negado sin motivo visible.
    cuerpo = _cuerpo_configuracion(await _configuracion(cliente, datos, base_url))
    cuerpo["limite_ejemplares"] = {"adulto": 0}

    r = await cliente.put(f"{base_url}/configuracion", headers=datos["admin"], json=cuerpo)
    assert r.status_code == 422


async def test_el_cambio_de_parametros_se_audita_solo(cliente, datos, base_url):
    cuerpo = _cuerpo_configuracion(await _configuracion(cliente, datos, base_url))
    await cliente.put(f"{base_url}/configuracion", headers=datos["admin"], json=cuerpo)

    eventos = await cliente.get(
        f"{base_url}/auditoria", params={"tipo": "cambio_config"}, headers=datos["biblio"])
    assert len(eventos.json()) == 1


# ── Aprendizaje ───────────────────────────────────────────────────────────────

async def test_un_lector_solo_registra_interacciones_propias(cliente, datos, base_url):
    titulo_id = await _crear_titulo(datos)

    propia = await cliente.post(f"{base_url}/aprendizaje/interacciones", headers=datos["lector"],
                                json={"lector_id": datos["lector_id"],
                                      "titulo_id": titulo_id, "tipo": "vista"})
    assert propia.status_code == 201, propia.text

    ajena = await cliente.post(f"{base_url}/aprendizaje/interacciones", headers=datos["otro"],
                               json={"lector_id": datos["lector_id"],
                                     "titulo_id": titulo_id, "tipo": "vista"})
    assert ajena.status_code == 403, "la señal se usa agregada: declarar por otro la ensucia"


async def test_las_correcciones_son_del_personal(cliente, datos, base_url):
    r = await cliente.post(f"{base_url}/aprendizaje/correcciones", headers=datos["biblio"], json={
        "campo": "autor", "valor_sugerido": "J. Cortazar", "valor_final": "Julio Cortázar",
    })
    assert r.status_code == 201, r.text

    listado = await cliente.get(
        f"{base_url}/aprendizaje/correcciones", headers=datos["biblio"])
    assert listado.json()[0]["valor_final"] == "Julio Cortázar"

    ajena = await cliente.get(
        f"{base_url}/aprendizaje/correcciones", headers=datos["lector"])
    assert ajena.status_code == 403


# ── Sin token ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ruta", [
    "/notificaciones", "/auditoria", "/configuracion", "/aprendizaje/interacciones",
    "/aprendizaje/correcciones",
])
async def test_ninguna_ruta_del_sistema_es_publica(cliente, base_url, ruta):
    r = await cliente.get(f"{base_url}{ruta}")
    assert r.status_code == 401


# ── Auxiliares ────────────────────────────────────────────────────────────────

_CAMPOS_CONFIGURACION = (
    "plazo_prestamo_dias", "limite_ejemplares", "limite_reservas",
    "plazo_retiro_reserva_horas", "multa_por_dia_demora", "recordatorio_antes_dias",
    "peso_historial_recomendacion", "min_prestamos_para_historial", "edad_mayoria_edad",
)


async def _configuracion(cliente, datos, base_url) -> dict:
    r = await cliente.get(f"{base_url}/configuracion", headers=datos["admin"])
    return r.json()


def _cuerpo_configuracion(cfg: dict) -> dict:
    return {campo: cfg[campo] for campo in _CAMPOS_CONFIGURACION}


async def _crear_titulo(datos) -> int:
    from app.models.libro import Titulo

    async with datos["sesion"]() as db:
        titulo = Titulo(titulo="Rayuela", autores="Julio Cortázar", isbn="9788437604947")
        db.add(titulo)
        await db.commit()
        await db.refresh(titulo)
        return titulo.id

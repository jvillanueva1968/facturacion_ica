from zeep import Client, Settings as ZeepSettings
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin
from zeep.wsse.signature import BinarySignature
from requests.auth import HTTPBasicAuth
import requests
from requests_pkcs12 import Pkcs12Adapter
from pathlib import Path
import ssl
import logging
from decimal import Decimal
from typing import Optional, List, Dict, Any
from app.config import get_settings
from app.models.schemas import (
    SNRIFacturaSimpleRequest,
    SNRIFacturaDetalleRequest,
    SNRIFacturaResponse,
    TerceroResponse,
    TerceroCreateRequest,
    InicioTransaccionRequest,
    TokenResponse,
    SNRIFormaPago,
    SNRIBanco,
    SNRIServicio,
    SNRISeccional,
    SNRIDepartamento,
    SNRICiudad,
    SNRITipoDocumento,
    SNRITipoPersona,
    FacturaImpresaResponse,
    dividir_nombre_en_partes,
    componer_nombre_persona,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class SNRIClient:
    _instance: Optional["SNRIClient"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self.client: Optional[Client] = None
        self.history = HistoryPlugin()
        self._token: Optional[str] = None
        self._ciudades_cache: Optional[List[SNRICiudad]] = None
        self._initialized = True
        self._initialize_client()

    @classmethod
    def reset_singleton(cls) -> None:
        cls._instance = None

    def _initialize_client(self):
        session = self._create_session_with_cert()
        transport = Transport(session=session, timeout=settings.snri_timeout)

        zeep_settings = ZeepSettings(
            strict=False,
            xml_huge_tree=True,
            raw_response=False
        )

        wsdl_path = Path(settings.snri_wsdl_local_path)
        wsdl_url = str(wsdl_path) if wsdl_path.exists() else settings.snri_wsdl_url

        try:
            self.client = Client(
                wsdl=wsdl_url,
                transport=transport,
                settings=zeep_settings,
                plugins=[self.history]
            )
            logger.info(f"Cliente SNRI inicializado con WSDL: {wsdl_url}")
            logger.info(f"Operaciones disponibles: {[op for op in dir(self.client.service) if not op.startswith('_')]}")
        except Exception as e:
            logger.error(f"Error inicializando cliente SNRI: {e}")
            raise

    def _create_session_with_cert(self) -> requests.Session:
        session = requests.Session()

        if settings.snri_cert_path and Path(settings.snri_cert_path).exists():
            adapter = Pkcs12Adapter(
                pkcs12_filename=settings.snri_cert_path,
                pkcs12_password=settings.snri_cert_password
            )
            session.mount("https://webservices.ica.gov.co", adapter)
            session.mount("http://webservices.ica.gov.co", adapter)
            logger.info("Certificado cliente .p12 configurado para SNRI")
        else:
            logger.warning("No hay certificado cliente configurado - SNRI podría rechazar peticiones en producción")

        session.verify = True
        return session

    @staticmethod
    def _field(obj: Any, name: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    @classmethod
    def _collect_token_items(cls, response: Any) -> List[Any]:
        if response is None:
            return []
        if isinstance(response, (list, tuple)):
            return list(response)

        container = cls._field(response, "A_InicioTransaccionResult")
        if container is None:
            container = response
        else:
            response = container

        inner = cls._field(container, "Result")
        if inner is None:
            return [container]
        if isinstance(inner, (list, tuple)):
            return list(inner)
        return [inner]

    async def obtener_token(self, request: InicioTransaccionRequest) -> TokenResponse:
        if not self.client:
            raise RuntimeError("Cliente SNRI no inicializado")

        try:
            logger.info(f"Obteniendo token para proyecto {request.id_proyecto}")
            response = self.client.service.A_InicioTransaccion(
                **{
                    "idProyecto": request.id_proyecto,
                    "username": request.username,
                    "pass": request.pass_,
                    "ip": request.ip,
                    "proceso": request.proceso,
                }
            )

            token = None
            success = False
            errores = []
            items = self._collect_token_items(response)

            for item in items:
                item_token = self._field(item, "Token")
                item_success = self._field(item, "Success")
                if item_token:
                    token = str(item_token)
                    success = bool(item_success) if item_success is not None else True
                    break
                for err in self._field(item, "Errores") or self._field(item, "ListMensajeProyectoToken") or []:
                    errores.append(
                        {
                            "codigo": self._field(err, "Codigo") or self._field(err, "Id") or "",
                            "mensaje": self._field(err, "Mensaje") or str(err),
                        }
                    )
                msg = self._field(item, "Mensaje")
                if msg:
                    errores.append({"codigo": self._field(item, "Id") or "", "mensaje": str(msg)})

            if not token and not errores:
                token = self._field(response, "Token")
                if token:
                    token = str(token)
                    success = bool(self._field(response, "Success") or True)

            self._token = token
            logger.info(f"Token obtenido: {'OK' if success else 'FAIL'}")
            return TokenResponse(token=token or "", success=success, errores=errores)

        except Exception as e:
            logger.error(f"Error obteniendo token SNRI: {e}")
            return TokenResponse(token="", success=False, errores=[{"codigo": "EXCEPTION", "mensaje": str(e)}])

    @property
    def token(self) -> Optional[str]:
        return self._token

    @token.setter
    def token(self, value: str):
        self._token = value

    @classmethod
    def _consultas_items(cls, response: Any) -> List[Any]:
        """ResultadoConsultasE -> Result(ArrayOfConsultasE) -> ConsultasE[]"""
        if response is None:
            return []
        result = cls._field(response, "Result")
        if result is None:
            return []
        inner = cls._field(result, "ConsultasE")
        if isinstance(inner, (list, tuple)):
            return list(inner)
        if inner is not None:
            return [inner]
        if isinstance(result, (list, tuple)):
            return list(result)
        return [result]

    @classmethod
    def _errores_from_response(cls, response: Any) -> List[dict]:
        return cls._extraer_errores_snri(response)

    def _get_formas_pago(self) -> List[SNRIFormaPago]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.R_ConsultaFormasPago(token=self._token)
        formas = []
        for item in self._consultas_items(response):
            formas.append(SNRIFormaPago(
                id_forma_pago=str(self._field(item, "Id") or self._field(item, "IdFormaPago") or ""),
                descripcion=str(self._field(item, "Nombre") or self._field(item, "Descripcion") or "")
            ))
        return formas

    def _get_bancos(self) -> List[SNRIBanco]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.B_ConsultaBancos(token=self._token)
        bancos = []
        for item in self._consultas_items(response):
            bancos.append(SNRIBanco(
                id_banco=str(self._field(item, "Id") or self._field(item, "IdBanco") or ""),
                nombre=str(self._field(item, "Nombre") or "")
            ))
        return bancos

    def _get_servicios(self) -> List[SNRIServicio]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.D_ConsultaServicio(token=self._token)
        servicios = []
        for item in self._consultas_items(response):
            valor = self._field(item, "VALOR", self._field(item, "Valor"))
            servicios.append(SNRIServicio(
                id_servicio=str(self._field(item, "Id") or ""),
                codigo=str(self._field(item, "CODIGO_SERVICIO") or self._field(item, "Codigo") or self._field(item, "Id") or ""),
                descripcion=str(self._field(item, "Nombre") or self._field(item, "Descripcion") or ""),
                valor=str(valor) if valor is not None else None,
            ))
        return servicios

    def _get_seccionales(self) -> List[SNRISeccional]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.C_ConsultaSeccional(token=self._token)
        seccionales = []
        for item in self._consultas_items(response):
            seccionales.append(SNRISeccional(
                id_seccional=str(self._field(item, "Id") or self._field(item, "IdSeccional") or ""),
                nombre=str(self._field(item, "Nombre") or "")
            ))
        return seccionales

    # Códigos DANE de los 33 departamentos colombianos (I_ConsultaDepartamentos no lista con 0)
    _DANE_DEPTOS = (
        5, 8, 11, 13, 15, 17, 18, 19, 20, 23, 25, 27, 41, 44, 47,
        50, 52, 54, 63, 66, 68, 70, 73, 76, 81, 85, 86, 88, 91, 94, 95, 97, 99,
    )
    # IdDepartamento SNRI observados para Colombia (J1 id_pais=0 + DANE lookups)
    _CO_ID_DEPTOS = frozenset({
        1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        21, 22, 23, 24, 25, 26, 28, 29, 30, 31, 32, 33, 37, 38,
    })

    def _get_departamentos(self) -> List[SNRIDepartamento]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        departamentos: Dict[int, SNRIDepartamento] = {}
        for dane in self._DANE_DEPTOS:
            try:
                response = self.client.service.I_ConsultaDepartamentos(
                    token=self._token, codigoDane=dane
                )
            except Exception as e:
                logger.warning(f"I_ConsultaDepartamentos({dane}) falló: {e}")
                continue
            for item in self._consultas_items(response):
                id_dpto = self._int_or_none(
                    self._field(item, "Id")
                    or self._field(item, "ID_DEPARTAMENTO")
                    or self._field(item, "IdDepartamento")
                )
                nombre = str(self._field(item, "Nombre") or self._field(item, "DEPARTAMENTO") or "")
                if id_dpto is None or not nombre:
                    continue
                departamentos[id_dpto] = SNRIDepartamento(
                    id_departamento=id_dpto, nombre=nombre
                )
        return sorted(departamentos.values(), key=lambda d: d.nombre)

    def _ciudades_all_co(self) -> List[SNRICiudad]:
        """J1_ConsultaCiudades_pais(id_pais=0) devuelve el catálogo global; filtramos Colombia."""
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        if getattr(self, "_ciudades_cache", None) is not None:
            return self._ciudades_cache

        response = self.client.service.J1_ConsultaCiudades_pais(
            token=self._token, id_pais=0
        )
        ciudades: List[SNRICiudad] = []
        for item in self._consultas_items(response):
            id_dpto = self._int_or_none(self._field(item, "IdDepartamento"))
            id_ciudad = self._int_or_none(
                self._field(item, "Id") or self._field(item, "ID_CIUDAD")
            )
            if id_ciudad is None or id_dpto not in self._CO_ID_DEPTOS:
                continue
            ciudades.append(SNRICiudad(
                id_ciudad=id_ciudad,
                nombre=str(self._field(item, "Nombre") or "").strip(),
                id_departamento=id_dpto,
            ))
        self._ciudades_cache = ciudades
        return ciudades

    def _get_ciudades(self, id_departamento: int) -> List[SNRICiudad]:
        return [
            c for c in self._ciudades_all_co()
            if c.id_departamento == id_departamento
        ]

    def _get_tipos_documento(self) -> List[SNRITipoDocumento]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.H_ConsultaTipoDocumentos(token=self._token)
        tipos = []
        for item in self._consultas_items(response):
            id_td = self._int_or_none(self._field(item, "Id") or self._field(item, "IdTipoDocumento"))
            if id_td is None:
                continue
            tipos.append(SNRITipoDocumento(
                id_tipo_documento=id_td,
                descripcion=str(self._field(item, "Nombre") or self._field(item, "Descripcion") or "")
            ))
        return tipos

    def _get_tipos_persona(self) -> List[SNRITipoPersona]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.L_ConsultaTiposPersona(token=self._token)
        tipos = []
        for item in self._consultas_items(response):
            id_tp = self._int_or_none(self._field(item, "Id") or self._field(item, "IdTipoPersona"))
            if id_tp is None:
                continue
            tipos.append(SNRITipoPersona(
                id_tipo_persona=id_tp,
                descripcion=str(self._field(item, "Nombre") or self._field(item, "Descripcion") or "")
            ))
        return tipos

    async def consultar_tercero(self, nro_identificacion: str) -> TerceroResponse:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        try:
            # SNRI espera solo el número de documento, sin DV ni guion
            documento = "".join(filter(str.isdigit, nro_identificacion or ""))
            if not documento:
                return TerceroResponse(success=False, errores=[{"codigo": "EMPTY", "mensaje": "Documento vacío"}])

            response = self.client.service.E_ConsultaTercero(
                token=self._token,
                documento=documento
            )

            return self._parse_tercero_response(response, documento)

        except Exception as e:
            logger.error(f"Error consultando tercero: {e}")
            return TerceroResponse(success=False, errores=[{"codigo": "EXCEPTION", "mensaje": str(e)}])

    def _parse_tercero_response(self, response: Any, documento: str) -> TerceroResponse:
        if response is None:
            return TerceroResponse(success=False, errores=[{"codigo": "NO_RESPONSE", "mensaje": "Respuesta vacía"}])

        success = bool(self._field(response, "Success"))
        result = self._field(response, "Result")
        items: List[Any] = []
        if result is not None:
            inner = self._field(result, "ConsultasE") or self._field(result, "Result")
            if isinstance(inner, (list, tuple)):
                items = list(inner)
            elif inner is not None:
                items = [inner]
            else:
                items = [result]

        item = None
        for cand in items:
            if self._field(cand, "Nombre") or self._field(cand, "NitCc") or self._field(cand, "Id") is not None:
                item = cand
                break

        if item is not None:
            nit_cc = str(self._field(item, "NitCc") or self._field(item, "NroIdentificacion") or documento)
            # base sin DV si viene "93361223" o con DV
            base = "".join(filter(str.isdigit, nit_cc))
            nombre = str(self._field(item, "Nombre") or self._field(item, "NombreRazonSocial") or "")
            tipo_persona_txt = str(
                self._field(item, "TIPO_PERSONA")
                or self._field(item, "TipoPersona")
                or self._field(item, "Id_tipo_persona")
                or ""
            ).upper()
            # 2 = jurídica / razón social; 1 = natural (nombres + apellidos)
            if "JURID" in tipo_persona_txt or "SOCIEDAD" in tipo_persona_txt or "EMPRES" in tipo_persona_txt:
                id_tipo_persona = 2
            elif "NATURAL" in tipo_persona_txt or "PERSONA NATURAL" in tipo_persona_txt:
                id_tipo_persona = 1
            else:
                # SNRI: Id_tipo_doc=1 → CEDULA (natural); Id_tipo_doc=2 → NIT (jurídica)
                id_doc = self._int_or_none(self._field(item, "Id_tipo_doc") or self._field(item, "IdTipoDocumento"))
                tipo_doc_txt = str(self._field(item, "Tipo_Documento") or "").upper()
                if "NIT" in tipo_doc_txt or id_doc == 2:
                    id_tipo_persona = 2
                elif "CEDULA" in tipo_doc_txt or id_doc == 1:
                    id_tipo_persona = 1
                else:
                    id_tipo_persona = 1

            if id_tipo_persona == 2:
                primer_nombre = segundo_nombre = primer_apellido = segundo_apellido = None
            else:
                partes = dividir_nombre_en_partes(nombre)
                primer_nombre = partes["primer_nombre"]
                segundo_nombre = partes["segundo_nombre"]
                primer_apellido = partes["primer_apellido"]
                segundo_apellido = partes["segundo_apellido"]

            return TerceroResponse(
                id_tercero=int(self._field(item, "Id") or self._field(item, "IdTercero") or 0) or None,
                nro_identificacion=base,
                nombre_razon_social=nombre,
                primer_nombre=primer_nombre,
                segundo_nombre=segundo_nombre,
                primer_apellido=primer_apellido,
                segundo_apellido=segundo_apellido,
                id_tipo_documento=self._int_or_none(self._field(item, "Id_tipo_doc") or self._field(item, "IdTipoDocumento")),
                id_tipo_persona=id_tipo_persona,
                gran_contribuyente=1 if str(self._field(item, "GRAN_CONTRIBUYENTE") or "").upper() == "SI" else 0,
                autorretenedor=1 if str(self._field(item, "AUTORRETENEDOR") or "").upper() == "SI" else 0,
                regimen_comun=1 if str(self._field(item, "REGIMEN_COMUN") or "").upper() == "SI" else 0,
                regimen_simplificado=1 if str(self._field(item, "REGIMEN_SIMPLIFICADO") or "").upper() == "SI" else 0,
                id_departamento=self._int_or_none(self._field(item, "ID_DEPARTAMENTO") or self._field(item, "IdDepartamento")),
                id_ciudad=self._int_or_none(self._field(item, "ID_CIUDAD") or self._field(item, "IdCiudad")),
                direccion_principal=str(self._field(item, "DireccionPrincipal") or ""),
                telefono=str(self._field(item, "TELEFONO") or self._field(item, "Telefono") or ""),
                email=str(self._field(item, "EMAIL") or self._field(item, "Email") or ""),
                success=success or True,
                errores=[]
            )

        errores = self._extraer_errores_snri(response)
        if not errores:
            errores = [{"codigo": "NO_ENCONTRADO", "mensaje": "Tercero no existe en SNRI"}]
        return TerceroResponse(success=False, errores=errores)

    @staticmethod
    def _int_or_none(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @classmethod
    def _extraer_errores_snri(cls, response: Any) -> List[dict]:
        errores: List[dict] = []
        if response is None:
            return errores
        err_container = cls._field(response, "Errores")
        mensajes = []
        if err_container is not None:
            mensajes = (
                cls._field(err_container, "MensajesFacturacionE")
                or cls._field(err_container, "Result")
                or []
            )
            if isinstance(mensajes, dict) or not isinstance(mensajes, (list, tuple)):
                mensajes = [mensajes]
        for m in mensajes or []:
            desc = cls._field(m, "Descripcion") or cls._field(m, "Mensaje") or str(m)
            code = cls._field(m, "IdMensaje") or cls._field(m, "Codigo") or cls._field(m, "Id") or ""
            errores.append({"codigo": str(code), "mensaje": str(desc)})
        msg = cls._field(response, "Mensaje")
        if msg and not errores:
            errores.append({"codigo": str(cls._field(response, "Id") or ""), "mensaje": str(msg)})
        return errores

    async def crear_tercero(self, request: TerceroCreateRequest) -> TerceroResponse:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        try:
            response = self.client.service.F_CrearTercero(
                token=request.token,
                idTipoDocumento=request.id_tipo_documento,
                idTipoPersona=request.id_tipo_persona,
                granContribuyente=request.gran_contribuyente,
                autorretenedor=request.autorretenedor,
                regimenComun=request.regimen_comun,
                regimenSimplificado=request.regimen_simplificado,
                nroIdentificacion=request.nro_identificacion,
                nombreRazonSocial=request.nombre_razon_social,
                idDepartamento=request.id_departamento,
                idCiudad=request.id_ciudad,
                direccionPrincipal=request.direccion_principal,
                telefono=request.telefono or "",
                email=request.email or "",
                representanteLegal=request.representante_legal or "",
                primernombre=request.primernombre or "",
                segundonombre=request.segundonombre or "",
                primerapellido=request.primerapellido or "",
                segundoapellido=request.segundoapellido or ""
            )

            if response and hasattr(response, 'Result') and response.Result:
                item = response.Result
                return TerceroResponse(
                    id_tercero=int(getattr(item, 'IdTercero', 0)) if getattr(item, 'IdTercero', None) else None,
                    nro_identificacion=str(getattr(item, 'NroIdentificacion', '')),
                    nombre_razon_social=str(getattr(item, 'NombreRazonSocial', '')),
                    success=True,
                    errores=[]
                )

            errores = []
            if response and hasattr(response, 'Errores') and response.Errores:
                for err in response.Errores:
                    errores.append({"codigo": getattr(err, 'Codigo', ''), "mensaje": getattr(err, 'Mensaje', '')})

            return TerceroResponse(success=False, errores=errores)

        except Exception as e:
            logger.error(f"Error creando tercero: {e}")
            return TerceroResponse(success=False, errores=[{"codigo": "EXCEPTION", "mensaje": str(e)}])

    def _factura_kwargs_base(self, request: SNRIFacturaSimpleRequest | SNRIFacturaDetalleRequest) -> Dict[str, Any]:
        """Mapea request interno → parámetros reales del WSDL M_CrearFactura / Alterna."""
        return {
            "token": request.token,
            "codigoServicios": int(request.id_servicio) if request.id_servicio and str(request.id_servicio).isdigit() else int(request.detalles[0].id_servicio) if getattr(request, "detalles", None) else 0,
            "idSeccional": int(request.id_seccional),
            "idTercero": int(request.id_tercero),
            "idFormaPago": int(request.id_forma_pago),
            "cantidad": int(request.cantidad) if getattr(request, "cantidad", None) else (
                sum(int(d.cantidad) for d in request.detalles) if getattr(request, "detalles", None) else 1
            ),
            "valor": request.valor if getattr(request, "valor", None) else (
                str(sum(Decimal(d.valor) * int(d.cantidad) for d in request.detalles)) if getattr(request, "detalles", None) else "0"
            ),
            "valorTotal": request.valor_total if getattr(request, "valor_total", None) else (
                str(sum(Decimal(d.valor_total) for d in request.detalles)) if getattr(request, "detalles", None) else "0"
            ),
            "IdBanco": str(request.id_banco or ""),
            "NumConsignacion": str(request.numero_consignacion or ""),
        }

    async def crear_factura_simple(self, request: SNRIFacturaSimpleRequest) -> SNRIFacturaResponse:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        try:
            logger.info(f"Creando factura simple para NIT {request.nro_identificacion}")
            kwargs = self._factura_kwargs_base(request)
            response = self.client.service.M_CrearFactura(**kwargs)
            return self._parse_factura_response(response)

        except Exception as e:
            logger.error(f"Error creando factura simple: {e}")
            self._log_soap_debug()
            return SNRIFacturaResponse(success=False, errores=[{"codigo": "EXCEPTION", "mensaje": str(e)}])

    async def crear_factura_detalle(self, request: SNRIFacturaDetalleRequest) -> SNRIFacturaResponse:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        try:
            logger.info(f"Creando factura detalle para NIT {request.nro_identificacion} con {len(request.detalles)} servicios")

            detalles = []
            for d in request.detalles:
                detalles.append({
                    "IdCodigoServicio": int(d.id_servicio),
                    "ValorTarifa": Decimal(str(d.valor)),
                    "Cantidad": int(d.cantidad),
                    "ValorTotal": Decimal(str(d.valor_total)),
                })

            kwargs = self._factura_kwargs_base(request)
            # WSDL: Detalles es ArrayOfFacturaDetalleE con hijo FacturaDetalleE
            kwargs["Detalles"] = {"FacturaDetalleE": detalles}
            response = self.client.service.M_CrearFacturaAlterna(**kwargs)
            return self._parse_factura_response(response)

        except Exception as e:
            logger.error(f"Error creando factura detalle: {e}")
            self._log_soap_debug()
            return SNRIFacturaResponse(success=False, errores=[{"codigo": "EXCEPTION", "mensaje": str(e)}])

    def _parse_factura_response(self, response: Any) -> SNRIFacturaResponse:
        """ResultadoProyectoFacturacionE: Success, NumeroFra, Result(FacturaVenta), Errores."""
        if response is None:
            return SNRIFacturaResponse(success=False, errores=[{"codigo": "NO_RESPONSE", "mensaje": "Respuesta vacía"}])

        success = bool(self._field(response, "Success"))
        numero = self._field(response, "NumeroFra")
        result = self._field(response, "Result")
        if result is not None and not numero:
            numero = self._field(result, "Nrofactura") or self._field(result, "NumeroFactura")
        id_factura = None
        cufe = None
        if result is not None:
            id_factura = self._field(result, "IdFactura")
            cufe = self._field(result, "CUFE") or self._field(result, "CodigoBarras")

        errores = self._extraer_errores_snri(response)
        if success or numero:
            return SNRIFacturaResponse(
                numero_factura=str(numero or ""),
                id_factura=str(id_factura) if id_factura is not None else None,
                cufe=str(cufe) if cufe else None,
                success=True,
                errores=[],
            )
        if not errores:
            errores = [{"codigo": "SNRI_FAIL", "mensaje": "SNRI no confirmó la factura"}]
        return SNRIFacturaResponse(success=False, errores=errores)

    async def imprimir_factura(self, nro_factura: str) -> FacturaImpresaResponse:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        try:
            response = self.client.service.P_ImprimirFactura(
                token=self._token,
                nroFactura=nro_factura
            )

            if response:
                success = getattr(response, 'Success', False)
                pdf_base64 = None
                if success and hasattr(response, 'Result') and response.Result:
                    pdf_base64 = str(response.Result)

                errores = []
                if hasattr(response, 'Errores') and response.Errores:
                    for err in response.Errores:
                        errores.append({"codigo": getattr(err, 'Codigo', ''), "mensaje": getattr(err, 'Mensaje', '')})

                return FacturaImpresaResponse(success=success, pdf_base64=pdf_base64, errores=errores)

            return FacturaImpresaResponse(success=False, errores=[{"codigo": "NO_RESPONSE", "mensaje": "Respuesta vacía"}])

        except Exception as e:
            logger.error(f"Error imprimiendo factura: {e}")
            return FacturaImpresaResponse(success=False, errores=[{"codigo": "EXCEPTION", "mensaje": str(e)}])

    async def consultar_factura_consignacion(self, numero_consignacion: str, id_proyecto: str, fecha_creacion: str = "", id_banco: str = "", ticket: str = "") -> Dict:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        try:
            response = self.client.service.Z_ConsultaFacturaConsignacion(
                token=self._token,
                id_Proyecto=id_proyecto,
                NumeroConsignacion=numero_consignacion,
                FechaCreacion=fecha_creacion,
                IdBanco=id_banco,
                Ticket=ticket
            )
            return {"success": True, "data": response}
        except Exception as e:
            logger.error(f"Error consultando factura por consignación: {e}")
            return {"success": False, "error": str(e)}

    async def validar_disponibilidad(self) -> bool:
        if not self.client:
            return False
        try:
            response = self.client.service.V_Ping()
            return True
        except Exception:
            return False

    def _log_soap_debug(self):
        if self.history.last_sent:
            logger.debug(f"SOAP Request: {self.history.last_sent['envelope']}")
        if self.history.last_received:
            logger.debug(f"SOAP Response: {self.history.last_received['envelope']}")

    def get_catalogos(self) -> Dict[str, List]:
        if not self._token:
            raise RuntimeError("Token no disponible. Llame obtener_token() primero.")

        return {
            "formas_pago": self._get_formas_pago(),
            "bancos": self._get_bancos(),
            "servicios": self._get_servicios(),
            "seccionales": self._get_seccionales(),
            "departamentos": self._get_departamentos(),
            "tipos_documento": self._get_tipos_documento(),
            "tipos_persona": self._get_tipos_persona(),
        }
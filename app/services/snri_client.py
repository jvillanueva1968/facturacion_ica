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
)

logger = logging.getLogger(__name__)
settings = get_settings()


class SNRIClient:
    def __init__(self):
        self.client: Optional[Client] = None
        self.history = HistoryPlugin()
        self._token: Optional[str] = None
        self._initialize_client()

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

    def _get_formas_pago(self) -> List[SNRIFormaPago]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.R_ConsultaFormasPago(token=self._token)
        formas = []
        if response and hasattr(response, 'Result') and response.Result:
            for item in response.Result:
                formas.append(SNRIFormaPago(
                    id_forma_pago=str(getattr(item, 'IdFormaPago', '')),
                    descripcion=str(getattr(item, 'Descripcion', ''))
                ))
        return formas

    def _get_bancos(self) -> List[SNRIBanco]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.B_ConsultaBancos(token=self._token)
        bancos = []
        if response and hasattr(response, 'Result') and response.Result:
            for item in response.Result:
                bancos.append(SNRIBanco(
                    id_banco=str(getattr(item, 'IdBanco', '')),
                    nombre=str(getattr(item, 'Nombre', ''))
                ))
        return bancos

    def _get_servicios(self) -> List[SNRIServicio]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.D_ConsultaServicio(token=self._token)
        servicios = []
        if response and hasattr(response, 'Result') and response.Result:
            for item in response.Result:
                servicios.append(SNRIServicio(
                    id_servicio=str(getattr(item, 'IdServicio', '')),
                    codigo=str(getattr(item, 'Codigo', '')),
                    descripcion=str(getattr(item, 'Descripcion', '')),
                    valor=str(getattr(item, 'Valor', '')) if hasattr(item, 'Valor') else None
                ))
        return servicios

    def _get_seccionales(self) -> List[SNRISeccional]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.C_ConsultaSeccional(token=self._token)
        seccionales = []
        if response and hasattr(response, 'Result') and response.Result:
            for item in response.Result:
                seccionales.append(SNRISeccional(
                    id_seccional=str(getattr(item, 'IdSeccional', '')),
                    nombre=str(getattr(item, 'Nombre', ''))
                ))
        return seccionales

    def _get_departamentos(self) -> List[SNRIDepartamento]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.I_ConsultaDepartamentos(token=self._token, codigoDane=0)
        departamentos = []
        if response and hasattr(response, 'Result') and response.Result:
            for item in response.Result:
                departamentos.append(SNRIDepartamento(
                    id_departamento=int(getattr(item, 'IdDepartamento', 0)),
                    nombre=str(getattr(item, 'Nombre', ''))
                ))
        return departamentos

    def _get_ciudades(self, id_departamento: int) -> List[SNRICiudad]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.J_ConsultaCiudades(token=self._token, codigoDane=id_departamento)
        ciudades = []
        if response and hasattr(response, 'Result') and response.Result:
            for item in response.Result:
                ciudades.append(SNRICiudad(
                    id_ciudad=int(getattr(item, 'IdCiudad', 0)),
                    nombre=str(getattr(item, 'Nombre', '')),
                    id_departamento=id_departamento
                ))
        return ciudades

    def _get_tipos_documento(self) -> List[SNRITipoDocumento]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.H_ConsultaTipoDocumentos(token=self._token)
        tipos = []
        if response and hasattr(response, 'Result') and response.Result:
            for item in response.Result:
                tipos.append(SNRITipoDocumento(
                    id_tipo_documento=int(getattr(item, 'IdTipoDocumento', 0)),
                    descripcion=str(getattr(item, 'Descripcion', ''))
                ))
        return tipos

    def _get_tipos_persona(self) -> List[SNRITipoPersona]:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        response = self.client.service.L_ConsultaTiposPersona(token=self._token)
        tipos = []
        if response and hasattr(response, 'Result') and response.Result:
            for item in response.Result:
                tipos.append(SNRITipoPersona(
                    id_tipo_persona=int(getattr(item, 'IdTipoPersona', 0)),
                    descripcion=str(getattr(item, 'Descripcion', ''))
                ))
        return tipos

    async def consultar_tercero(self, nro_identificacion: str) -> TerceroResponse:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        try:
            response = self.client.service.E_ConsultaTercero(
                token=self._token,
                nroIdentificacion=nro_identificacion
            )

            if response and hasattr(response, 'Result') and response.Result:
                item = response.Result
                return TerceroResponse(
                    id_tercero=int(getattr(item, 'IdTercero', 0)) if getattr(item, 'IdTercero', None) else None,
                    nro_identificacion=str(getattr(item, 'NroIdentificacion', '')),
                    nombre_razon_social=str(getattr(item, 'NombreRazonSocial', '')),
                    id_tipo_documento=int(getattr(item, 'IdTipoDocumento', 0)) if getattr(item, 'IdTipoDocumento', None) else None,
                    id_tipo_persona=int(getattr(item, 'IdTipoPersona', 0)) if getattr(item, 'IdTipoPersona', None) else None,
                    gran_contribuyente=int(getattr(item, 'GranContribuyente', 0)) if getattr(item, 'GranContribuyente', None) else None,
                    autorretenedor=int(getattr(item, 'Autorretenedor', 0)) if getattr(item, 'Autorretenedor', None) else None,
                    regimen_comun=int(getattr(item, 'RegimenComun', 0)) if getattr(item, 'RegimenComun', None) else None,
                    regimen_simplificado=int(getattr(item, 'RegimenSimplificado', 0)) if getattr(item, 'RegimenSimplificado', None) else None,
                    id_departamento=int(getattr(item, 'IdDepartamento', 0)) if getattr(item, 'IdDepartamento', None) else None,
                    id_ciudad=int(getattr(item, 'IdCiudad', 0)) if getattr(item, 'IdCiudad', None) else None,
                    direccion_principal=str(getattr(item, 'DireccionPrincipal', '')),
                    telefono=str(getattr(item, 'Telefono', '')),
                    email=str(getattr(item, 'Email', '')),
                    success=True,
                    errores=[]
                )

            errores = []
            if response and hasattr(response, 'Errores') and response.Errores:
                for err in response.Errores:
                    errores.append({"codigo": getattr(err, 'Codigo', ''), "mensaje": getattr(err, 'Mensaje', '')})

            return TerceroResponse(success=False, errores=errores)

        except Exception as e:
            logger.error(f"Error consultando tercero: {e}")
            return TerceroResponse(success=False, errores=[{"codigo": "EXCEPTION", "mensaje": str(e)}])

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

    async def crear_factura_simple(self, request: SNRIFacturaSimpleRequest) -> SNRIFacturaResponse:
        if not self.client or not self._token:
            raise RuntimeError("Cliente o token no inicializado")

        try:
            logger.info(f"Creando factura simple para NIT {request.nro_identificacion}")
            response = self.client.service.M_CrearFactura(
                token=request.token,
                idProyecto=request.id_proyecto,
                idSeccional=request.id_seccional,
                idEntidad=request.id_entidad,
                idTercero=request.id_tercero,
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
                idFormaPago=request.id_forma_pago,
                idBanco=request.id_banco,
                numeroConsignacion=request.numero_consignacion,
                fechaConsignacion=request.fecha_consignacion,
                idServicio=request.id_servicio,
                valor=request.valor,
                cantidad=request.cantidad,
                valorTotal=request.valor_total,
                observaciones=request.observaciones or "",
                ticketId=request.ticket_id or ""
            )

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
                    'idServicio': d.id_servicio,
                    'valor': d.valor,
                    'cantidad': d.cantidad,
                    'valorTotal': d.valor_total
                })

            response = self.client.service.M_CrearFacturaAlterna(
                token=request.token,
                idProyecto=request.id_proyecto,
                idSeccional=request.id_seccional,
                idEntidad=request.id_entidad,
                idTercero=request.id_tercero,
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
                idFormaPago=request.id_forma_pago,
                idBanco=request.id_banco,
                numeroConsignacion=request.numero_consignacion,
                fechaConsignacion=request.fecha_consignacion,
                observaciones=request.observaciones or "",
                Detalles={'FacturaDetalle': detalles}
            )

            return self._parse_factura_response(response)

        except Exception as e:
            logger.error(f"Error creando factura detalle: {e}")
            self._log_soap_debug()
            return SNRIFacturaResponse(success=False, errores=[{"codigo": "EXCEPTION", "mensaje": str(e)}])

    def _parse_factura_response(self, response: Any) -> SNRIFacturaResponse:
        if not response or not hasattr(response, 'Result') or not response.Result:
            errores = []
            if response and hasattr(response, 'Errores') and response.Errores:
                for err in response.Errores:
                    errores.append({"codigo": getattr(err, 'Codigo', ''), "mensaje": getattr(err, 'Mensaje', '')})
            return SNRIFacturaResponse(success=False, errores=errores)

        item = response.Result
        success = getattr(item, 'Success', False)

        if success:
            return SNRIFacturaResponse(
                numero_factura=str(getattr(item, 'NumeroFactura', '')),
                id_factura=str(getattr(item, 'IdFactura', '')),
                cufe=str(getattr(item, 'CUFE', '')) if hasattr(item, 'CUFE') else None,
                success=True,
                errores=[]
            )
        else:
            errores = []
            if hasattr(item, 'Errores') and item.Errores:
                for err in item.Errores:
                    errores.append({"codigo": getattr(err, 'Codigo', ''), "mensaje": getattr(err, 'Mensaje', '')})
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
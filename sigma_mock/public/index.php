<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Headers: Content-Type, X-API-Token');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

$EXPECTED_TOKEN = getenv('SIGMA_API_TOKEN') ?: 'dev-sigma-token';
$provided = $_SERVER['HTTP_X_API_TOKEN'] ?? '';

$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?: '';
$path = rtrim($path, '/');
// Acepta /facturas/registrar y /api/facturas/registrar
if ($path === '/facturas/registrar' || $path === '/facturas/consultar') {
    $path = '/api' . $path;
}

function fail(int $code, string $msg): void {
    http_response_code($code);
    echo json_encode(['success' => false, 'error' => $msg], JSON_UNESCAPED_UNICODE);
    exit;
}

function ok(array $extra = []): void {
    echo json_encode(array_merge(['success' => true], $extra), JSON_UNESCAPED_UNICODE);
    exit;
}

if ($path === '/api/health' || $path === '/health') {
    ok(['service' => 'sigma-mock', 'time' => gmdate('c')]);
}

if ($EXPECTED_TOKEN !== '' && $provided !== $EXPECTED_TOKEN) {
    fail(401, 'X-API-Token inválido');
}

$raw = file_get_contents('php://input') ?: '';
$data = json_decode($raw, true);
if ($path !== '/api/facturas/consultar' && !is_array($data)) {
    fail(400, 'JSON inválido');
}

if ($path === '/api/facturas/registrar') {
    $ref = (string)($data['numero_referencia'] ?? $data['numero_consignacion'] ?? '');
    if ($ref === '') {
        fail(422, 'numero_referencia requerido');
    }

    $store = getenv('SIGMA_STORE') ?: '/tmp/sigma_mock_store.json';
    $rows = [];
    if (is_readable($store)) {
        $decoded = json_decode((string)file_get_contents($store), true);
        if (is_array($decoded)) {
            $rows = $decoded;
        }
    }

    // Idempotencia por numero_referencia
    foreach ($rows as $row) {
        if (($row['numero_referencia'] ?? '') === $ref) {
            ok([
                'id' => $row['id'],
                'numero_referencia' => $ref,
                'duplicado' => true,
                'registrado_en' => $row['registrado_en'] ?? null,
            ]);
        }
    }

    $id = bin2hex(random_bytes(8));
    $row = [
        'id' => $id,
        'numero_referencia' => $ref,
        'numero_factura_snri' => $data['numero_factura_snri'] ?? null,
        'cufe' => $data['cufe'] ?? null,
        'nit_facturar' => $data['nit_facturar'] ?? null,
        'dv_facturar' => $data['dv_facturar'] ?? null,
        'forma_pago' => $data['forma_pago'] ?? null,
        'valor_total' => $data['valor_total'] ?? null,
        'fecha_factura' => $data['fecha_factura'] ?? null,
        'servicios' => $data['servicios'] ?? [],
        'payload' => $data,
        'registrado_en' => gmdate('c'),
    ];
    $rows[] = $row;
    file_put_contents($store, json_encode($rows, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));

    ok([
        'id' => $id,
        'numero_referencia' => $ref,
        'duplicado' => false,
        'registrado_en' => $row['registrado_en'],
    ]);
}

if ($path === '/api/facturas/consultar') {
    $ref = (string)($_GET['numero_referencia'] ?? '');
    if ($ref === '') {
        fail(422, 'numero_referencia requerido');
    }
    $store = getenv('SIGMA_STORE') ?: '/tmp/sigma_mock_store.json';
    $rows = [];
    if (is_readable($store)) {
        $decoded = json_decode((string)file_get_contents($store), true);
        if (is_array($decoded)) {
            $rows = $decoded;
        }
    }
    foreach ($rows as $row) {
        if (($row['numero_referencia'] ?? '') === $ref) {
            ok($row);
        }
    }
    fail(404, 'No encontrada');
}

fail(404, 'Ruta no encontrada: ' . $path);

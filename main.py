from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import requests
import json
from typing import Dict, Any, Optional, Tuple
from functools import partial
import asyncio
from datetime import datetime
import uvicorn

# Configurações imutáveis
CONFIG = {
    "VALID_TOKEN": "a3a6e3d2f1b4c9e8d7a6b5c4d3e2f1a0b9c8d7e6f5a4b3", #token secreto
    "CONFIRMATION_URL": "http://localhost:5001/confirmar", #url de confirmação
    "CANCELLATION_URL": "http://localhost:5001/cancelar", #url de cancelamento
    "VALID_EVENTS": ["payment_success"], #eventos validos
    "VALID_CURRENCIES": ["BRL", "USD", "EUR"], #moedas validas
    "MIN_AMOUNT": 0.01, #valor minimo
    "MAX_AMOUNT": 999999.99 #valor maximo
}

# Estado para controlar transações processadas (simulando persistência)
processed_transactions = set()

app = FastAPI(title="Webhook Payment Service")

# Funções puras para validação
def validate_token(token: Optional[str]) -> bool:
    """Valida se o token é válido"""
    return token == CONFIG["VALID_TOKEN"]

def validate_required_fields(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Valida se todos os campos obrigatórios estão presentes"""
    required_fields = ["event", "transaction_id", "amount", "currency"]
    missing_fields = [field for field in required_fields if field not in payload]
    
    if missing_fields:
        return False, f"Campos obrigatórios ausentes: {', '.join(missing_fields)}"
    return True, ""

def validate_event(event: str) -> bool:
    """Valida se o evento é válido"""
    return event in CONFIG["VALID_EVENTS"]

def validate_amount(amount: Any) -> bool:
    """Valida se o valor é válido"""
    try:
        amount_float = float(amount)
        return CONFIG["MIN_AMOUNT"] <= amount_float <= CONFIG["MAX_AMOUNT"]
    except (ValueError, TypeError):
        return False

def validate_currency(currency: str) -> bool:
    """Valida se a moeda é válida"""
    return currency in CONFIG["VALID_CURRENCIES"]

def validate_transaction_id(transaction_id: str) -> bool:
    """Valida se o transaction_id não está vazio"""
    return bool(transaction_id and transaction_id.strip())

def is_duplicate_transaction(transaction_id: str) -> bool:
    """Verifica se a transação já foi processada"""
    return transaction_id in processed_transactions

def validate_payload_structure(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Valida a estrutura completa do payload"""
    # Verifica campos obrigatórios
    is_valid, error_msg = validate_required_fields(payload)
    if not is_valid:
        return False, error_msg
    
    # Valida evento
    if not validate_event(payload["event"]):
        return False, f"Evento inválido: {payload['event']}"
    
    # Valida transaction_id
    if not validate_transaction_id(payload["transaction_id"]):
        return False, "Transaction ID inválido"
    
    # Valida amount
    if not validate_amount(payload["amount"]):
        return False, f"Valor inválido: {payload['amount']}"
    
    # Valida currency
    if not validate_currency(payload["currency"]):
        return False, f"Moeda inválida: {payload['currency']}"
    
    return True, ""

# Funções para processamento de transações
def make_http_request(url: str, data: Dict[str, Any]) -> bool:
    """Faz requisição HTTP para URL especificada"""
    try:
        response = requests.post(url, json=data, timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

def confirm_transaction(transaction_data: Dict[str, Any]) -> bool:
    """Confirma uma transação válida"""
    return make_http_request(CONFIG["CONFIRMATION_URL"], transaction_data)

def cancel_transaction(transaction_data: Dict[str, Any]) -> bool:
    """Cancela uma transação inválida"""
    return make_http_request(CONFIG["CANCELLATION_URL"], transaction_data)

def add_to_processed(transaction_id: str) -> None:
    """Adiciona transação ao conjunto de processadas"""
    processed_transactions.add(transaction_id)

def process_valid_transaction(payload: Dict[str, Any]) -> Tuple[int, str]:
    """Processa uma transação válida"""
    transaction_id = payload["transaction_id"]
    
    # Verifica duplicação
    if is_duplicate_transaction(transaction_id):
        return 400, "Transação duplicada"
    
    # Adiciona à lista de processadas
    add_to_processed(transaction_id)
    
    # Confirma a transação
    if confirm_transaction(payload):
        return 200, "Transação confirmada com sucesso"
    else:
        return 500, "Erro ao confirmar transação"

def process_invalid_transaction(payload: Dict[str, Any], error_msg: str) -> Tuple[int, str]:
    """Processa uma transação inválida"""
    # Para transações inválidas, tentamos cancelar se temos transaction_id
    if "transaction_id" in payload and payload["transaction_id"]:
        cancel_transaction(payload)
    
    return 400, f"Transação inválida: {error_msg}"

# Função principal de processamento
def process_webhook_payload(payload: Dict[str, Any]) -> Tuple[int, str]:
    """Processa o payload do webhook de forma funcional"""
    # Valida estrutura do payload
    is_valid, error_msg = validate_payload_structure(payload)
    
    if is_valid:
        return process_valid_transaction(payload)
    else:
        return process_invalid_transaction(payload, error_msg)

@app.post("/webhook")
async def webhook_handler(request: Request):
    """Endpoint principal do webhook"""
    try:
        # Extrai o token do header
        token = request.headers.get("X-Webhook-Token")
        
        # Valida token
        if not validate_token(token):
            raise HTTPException(status_code=401, detail="Token inválido")
        
        # Extrai o payload
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="JSON inválido")
        
        # Processa o payload
        status_code, message = process_webhook_payload(payload)
        
        if status_code == 200:
            return JSONResponse(
                status_code=status_code,
                content={"status": "success", "message": message}
            )
        else:
            return JSONResponse(
                status_code=status_code,
                content={"status": "error", "message": message}
            )
            
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Erro interno: {str(e)}"}
        )

@app.get("/health")
async def health_check():
    """Endpoint de verificação de saúde"""
    return {"status": "healthy", "processed_transactions": len(processed_transactions)}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)
# NetBox SNMP Discovery Simulator

## O que este projeto faz
Esta aplicação fornece uma API REST que simula a descoberta de dispositivos via SNMP (usando um arquivo JSON local `simulated_snmp_data.json`) e integra os dados com uma instância do NetBox via sua API REST. Ela cria/atualiza dispositivos, interfaces e endereços IP.

## Estrutura do projeto
- `app/` - código da aplicação FastAPI
- `simulated_snmp_data.json` - fonte de dados simulada (fornecida)
- `Dockerfile` - para construir a imagem da aplicação
- `docker-compose.yml` - orquestra NetBox, Postgres, Redis e sua API
- `README.md` - este arquivo

## Pré-requisitos
- Docker e Docker Compose instalados
- Pelo menos 4GB de RAM disponível (NetBox pode exigir recursos)

## Como rodar (modo recomendado)
1. Copie o arquivo `simulated_snmp_data.json` se necessário (já incluído).
2. Ajuste o token do NetBox no arquivo `docker-compose.yml` (variável `NETBOX_TOKEN`) ou exporte `NETBOX_TOKEN` no ambiente.
3. Execute:
   ```bash
   docker-compose up --build
   ```
4. O NetBox ficará disponível em `http://localhost:8001` e a API em `http://localhost:8000/api/v/discover`.

## Endpoint principal
`POST /api/v/discover`

### Corpo (JSON)
- `cidr` (opcional): faixa em CIDR. Exemplo: `192.168.1.0/29`
- `ips` (opcional): lista de IPs individuais a serem escaneados.
- `name_prefix` (opcional): prefixo para nomes de dispositivo (não utilizado pela implementação básica).

Exemplo:
```json
{ "cidr": "192.168.1.0/29" }
```

### Resposta de sucesso
A API retorna um JSON com resumo das ações realizadas:
```json
{
  "scanned": ["192.168.1.1", "..."],
  "created": [{"ip":"192.168.1.1","device":"core-router-sp-01"}],
  "updated": [],
  "skipped": [],
  "errors": []
}
```

## Detalhes de implementação / decisões de projeto
- Usei **FastAPI** para um desenvolvimento rápido e validação automática.
- A integração com NetBox é feita por chamadas HTTP diretas. Para facilitar testes locais sem NetBox configurado, a aplicação detecta a ausência de `NETBOX_URL`/`NETBOX_TOKEN` e apenas loga as operações sem executar chamadas.
- O mapeamento de tipos (device_type, site, etc.) foi simplificado — a criação de objetos relacionais no NetBox (device_type, site, etc.) não foi implementada na versão básica para manter o escopo simples. Esses campos podem ser mapeados posteriormente com buscas e criação de objetos auxiliares.
- Variáveis sensíveis (token) devem ser passadas via variáveis de ambiente (ou .env).

## Testando com curl
```bash
curl -X POST http://localhost:8000/api/v/discover -H "Content-Type: application/json" -d '{"cidr":"192.168.1.0/29"}'
```

## Pontos de melhoria (sugestões)
- Implementar criação/consulta de `device_type`, `site` e `device_role` no NetBox.
- Testes unitários e de integração.
- Melhor tratamento de erros e retries para chamadas ao NetBox.
- Sincronização para evitar duplicidade de interfaces ao rodar scans repetidos.

## Licença
MIT

# QuestHub — plataforma de questões

MVP funcional com Flask, SQLAlchemy, PostgreSQL, autenticação, banco colaborativo, filtros, dashboard, revisão após 7 dias, leaderboard e provas cronometradas.

## Rodar localmente

Requer Python 3.11+ (o Render está configurado para Python 3.12).

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

A configuração padrão usa SQLite local para facilitar o teste. Para PostgreSQL, defina `DATABASE_URL` com a URL do banco.

## Publicar no Render

1. Envie esta pasta para um repositório GitHub.
2. No Render, selecione **New > Blueprint** e conecte o repositório.
3. O `render.yaml` cria o serviço web e o PostgreSQL.
4. Confira se `SECRET_KEY` foi gerada e `DATABASE_URL` está vinculada ao banco.

**Persistência:** use um banco PostgreSQL persistente. O SQLite padrão é somente para desenvolvimento local. Faça backups periódicos do banco de produção.

## Funcionalidades

- Cadastro e login por e-mail, com hash seguro de senha.
- Cadastro colaborativo de questões com número variável de alternativas.
- Filtros por assunto, dificuldade e fonte.
- Gabarito e explicação após responder.
- Estado de revisão por usuário: “Respondida recentemente” por 7 dias; depois “É bom relembrar”.
- Dashboard e desempenho por assunto.
- Ranking por percentual de acertos (desempate por quantidade respondida).
- Provas com questões aleatórias, filtros, cronômetro validado pelo servidor e resultado final.
- Proteção CSRF nos formulários.

## Limitações conhecidas do MVP

- Questões são publicadas imediatamente após cadastro; moderação e denúncias podem ser adicionadas numa próxima versão.
- O ranking conta todas as tentativas; pode-se evoluir para ranking por questões únicas ou por período.
- A revisão é calculada pela última resposta de cada usuário. Responder novamente atualiza a data de revisão.
- Para produção em escala, recomenda-se migrações com Flask-Migrate/Alembic, testes automatizados, recuperação de senha por e-mail e rate limiting.


## Acesso sem e-mail
O cadastro e o login usam apenas nome de usuário e senha. O campo de e-mail não aparece na interface; para manter compatibilidade com bancos já existentes, a aplicação gera um identificador interno não utilizável como endereço real.

## Códigos de assunto e biblioteca de materiais

- Questões agora podem receber um código de assunto no formato `FIS003` (2–5 letras e 3 números). O banco de questões aceita busca pelo código.
- A aba **Materiais** reúne links externos, vídeos, resumos e fórmulas principais associados ao mesmo código.
- Usuários autenticados podem publicar materiais; os materiais ficam salvos no banco de dados compartilhado.
- Ao iniciar a versão atualizada, o app adiciona a coluna `subject_code` às tabelas de questões já existentes sem apagar as questões anteriores. Questões antigas permanecem sem código até serem atualizadas.

### Catálogo de códigos de matérias
Usuários autenticados podem abrir **Códigos** na navegação e cadastrar novos códigos (ex.: `FIS003` — Eletromagnetismo). O código é único; duplicatas são rejeitadas. A tabela `subject_code` é criada automaticamente pelo `db.create_all()` em instalações existentes, sem apagar os dados anteriores.

## Backup completo e lembrete de ciclo

- O menu **Backups** fica disponível somente para o usuário configurado em `BACKUP_ADMIN_USERNAME`.
- A página permite baixar um JSON com todas as tabelas da aplicação e restaurar esse arquivo. **Restaurar substitui todos os dados atuais**; baixe uma cópia atual antes de restaurar.
- Configure `BACKUP_ADMIN_USERNAME` nas Environment Variables do Render com o nome de usuário da conta responsável pelos backups.
- Configure `DATABASE_CREATED_AT` com a data/hora UTC em que o banco foi criado, em ISO 8601 (ex.: `2026-10-14T12:00:00+00:00`). `DATABASE_CYCLE_DAYS` é 30 por padrão. O site mostra um aviso no dia anterior ao próximo ciclo calculado.
- O lembrete é baseado na data configurada e não detecta nem impede a expiração real do serviço Render. Mantenha cópias baixadas fora do Render e faça backups frequentes.

## Recursos opcionais de IA (QuestHub)

Para ativar a organização de PDFs por IA, correção opcional de questões sem gabarito e geração de novas questões:

1. Adicione `GEMINI_API_KEY` nas variáveis de ambiente do serviço no Render. Nunca coloque a chave no HTML, JavaScript ou em um repositório público.
2. Opcionalmente configure `GEMINI_MODEL` (padrão: `gemini-3.8-flash`).
3. Faça um novo deploy para instalar a dependência `google-genai` declarada em `requirements.txt`.
4. Comece pelo nível gratuito disponível no Google AI Studio, sujeito a limites e disponibilidade do modelo. Confira as condições de privacidade: no nível gratuito, conteúdo enviado pode ser usado para melhorar os produtos do Google. Não envie dados pessoais ou sensíveis nos PDFs. Se mudar para um nível pago, confira os preços antes de ativá-lo.

### Fluxos

- **Importar PDF com IA:** marque a opção de organização por IA. O sistema mostra uma prévia e só grava as questões depois da aprovação explícita. O importador tradicional continua disponível.
- **Correção por IA:** depois de responder uma questão sem gabarito ou sem resposta de referência, o usuário pode escolher pedir uma análise. A sugestão não é gabarito oficial; respostas de múltipla escolha sem chave não entram na pontuação automática.
- **Criar questões com IA:** ao filtrar um assunto com mais de 10 questões existentes, usuários conectados veem a opção de gerar de 1 a 10 questões. A prévia precisa ser aprovada e as questões salvas recebem a tag “Elaborada por IA” e o estado “Não revisada”.

As funções de IA não apagam nem substituem questões existentes. Questões geradas devem ser verificadas por uma pessoa antes de serem usadas como material definitivo.

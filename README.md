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

# infra/ — Infrastructure as Code (AWS)  ·  Tier 3

IaC (CDK or Terraform) for the AWS stack: ECS Fargate / EC2 Graviton (agents + API), S3 + CloudFront
(frontend), Cognito (registration + RBAC), CloudWatch, the vector DB, and the SLM endpoint.

**`environments/dev` and `environments/prod` are environments, not repos or branches** — the same
artifact is promoted dev → prod by CI/CD (see [../docs/adr/0004-monorepo-and-environment-promotion.md](../docs/adr/0004-monorepo-and-environment-promotion.md)).
Only env-specific config/secrets differ between them.
</content>

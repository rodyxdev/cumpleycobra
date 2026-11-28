#![cfg(test)]

// Pruebas de v14 (concursos multi-ganador, retainers por ciclos, crowdfunding con
// reembolso proporcional, tareas en equipo, pagos por tiempo con cliff y conversiones).

extern crate std;

use super::test_v4::{setup, Ctx, Modo, DIA, MINT, START_TS, UNIT};
use super::test_v6::firmas;
use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger as _, MockAuth, MockAuthInvoke},
    Address, BytesN, IntoVal, String, Val, Vec,
};

fn cuadra(ctx: &Ctx) {
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));
}

fn h(env: &Env, b: u8) -> BytesN<32> {
    BytesN::from_array(env, &[b; 32])
}

fn firma_deposito(ctx: &Ctx, who: &Address, fn_name: &'static str, args: Vec<Val>, amount: i128) {
    let token_id = ctx.token.address.clone();
    ctx.env.mock_auths(&[MockAuth {
        address: who,
        invoke: &MockAuthInvoke {
            contract: &ctx.contract_id,
            fn_name,
            args,
            sub_invokes: &[MockAuthInvoke {
                contract: &token_id,
                fn_name: "transfer",
                args: (who, &ctx.contract_id, amount).into_val(&ctx.env),
                sub_invokes: &[],
            }],
        },
    }]);
}

#[test]
fn v14_bounty_multi_ganador_recarga_y_reembolso() {
    let ctx = setup(Modo::Libre);
    let id = String::from_str(&ctx.env, "bounty-1");
    let g2 = Address::generate(&ctx.env);

    // Abre concurso de 10 USDC a 1 día y un tercero aporta 5 unidades más.
    ctx.c.open_bounty(&ctx.client, &id, &(10 * UNIT), &DIA, &h(&ctx.env, 1));
    assert_eq!(
        ctx.c.try_open_bounty(&ctx.client, &id, &(2 * UNIT), &DIA, &h(&ctx.env, 1)),
        Err(Ok(Error::AlreadyExists))
    );
    assert_eq!(ctx.c.top_up_bounty(&ctx.third, &id, &5), 10 * UNIT + 5);

    // Reembolso antes del plazo falla con DeadlineNotReached.
    assert_eq!(ctx.c.try_refund_bounty(&id), Err(Ok(Error::DeadlineNotReached)));

    // El árbitro premia a dos ganadores distintos parcialmente (3 y 4 USDC).
    assert_eq!(
        ctx.c.award_bounty(&id, &ctx.freelancer, &(3 * UNIT), &h(&ctx.env, 2)),
        7 * UNIT + 5
    );
    assert_eq!(
        ctx.c.award_bounty(&id, &g2, &(4 * UNIT), &h(&ctx.env, 3)),
        3 * UNIT + 5
    );
    assert_eq!(ctx.token.balance(&ctx.freelancer), 3 * UNIT);
    assert_eq!(ctx.token.balance(&g2), 4 * UNIT);

    // Vence el plazo: cualquiera dispara el reembolso y lo no premiado (3 USDC + 5) vuelve al cliente.
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    assert_eq!(
        ctx.c.try_award_bounty(&id, &g2, &UNIT, &h(&ctx.env, 4)),
        Err(Ok(Error::DeadlinePassed))
    );
    assert_eq!(ctx.c.refund_bounty(&id), 3 * UNIT + 5);
    assert_eq!(ctx.c.try_refund_bounty(&id), Err(Ok(Error::NotFunded)));
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 7 * UNIT + 5);
    assert_eq!(ctx.token.balance(&ctx.third), 2);
    cuadra(&ctx);

    // Modo estricto: alguien que no es el árbitro no puede premiar el concurso.
    let est = setup(Modo::Estricto);
    let eid = String::from_str(&est.env, "bounty-strict");
    firma_deposito(
        &est,
        &est.client,
        "open_bounty",
        (&est.client, &eid, 2 * UNIT, DIA, &h(&est.env, 5)).into_val(&est.env),
        2 * UNIT,
    );
    est.c.open_bounty(&est.client, &eid, &(2 * UNIT), &DIA, &h(&est.env, 5));
    firmas(
        &est,
        &[&est.client],
        "award_bounty",
        (&eid, &est.freelancer, UNIT, &h(&est.env, 6)).into_val(&est.env),
    );
    assert!(est.c.try_award_bounty(&eid, &est.freelancer, &UNIT, &h(&est.env, 6)).is_err());
}

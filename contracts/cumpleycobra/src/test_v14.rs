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

#[test]
fn v14_retainer_ciclos_reembolso_y_cancelacion_mutua() {
    let ctx = setup(Modo::Libre);
    let rid = String::from_str(&ctx.env, "ret-1");

    // 3 ciclos de 2 USDC cada uno (1 día por ciclo = 6 USDC).
    assert_eq!(
        ctx.c.create_retainer(&ctx.client, &rid, &ctx.freelancer, &(2 * UNIT), &DIA, &3),
        6 * UNIT
    );
    assert_eq!(ctx.c.try_refund_expired_retainer_cycle(&rid), Err(Ok(Error::DeadlineNotReached)));

    // Ciclo 0 se libera antes de vencer -> quedan 2 ciclos.
    assert_eq!(ctx.c.release_retainer_cycle(&rid, &h(&ctx.env, 10)), 2);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 2 * UNIT);

    // Pasan 2 días: vence ciclo 1 (cycle_end = START_TS + 2*DIA), no se puede liberar, se reembolsa.
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    assert_eq!(
        ctx.c.try_release_retainer_cycle(&rid, &h(&ctx.env, 11)),
        Err(Ok(Error::DeadlinePassed))
    );
    assert_eq!(ctx.c.refund_expired_retainer_cycle(&rid), 1);

    // Cliente y programador acuerdan cerrar el ciclo 2 restante -> devuelve 2 USDC.
    assert_eq!(ctx.c.cancel_retainer(&rid), 2 * UNIT);
    assert_eq!(ctx.c.try_cancel_retainer(&rid), Err(Ok(Error::NotFunded)));
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 2 * UNIT);
    cuadra(&ctx);

    // Modo estricto: `cancel_retainer` falla si solo firma el cliente (sin el programador).
    let est = setup(Modo::Estricto);
    let erid = String::from_str(&est.env, "ret-strict");
    firma_deposito(
        &est,
        &est.client,
        "create_retainer",
        (&est.client, &erid, &est.freelancer, UNIT, DIA, 2u32).into_val(&est.env),
        2 * UNIT,
    );
    est.c.create_retainer(&est.client, &erid, &est.freelancer, &UNIT, &DIA, &2);
    firmas(&est, &[&est.client], "cancel_retainer", (&erid,).into_val(&est.env));
    assert!(est.c.try_cancel_retainer(&erid).is_err());
    firmas(&est, &[&est.client, &est.freelancer], "cancel_retainer", (&erid,).into_val(&est.env));
    assert_eq!(est.c.cancel_retainer(&erid), 2 * UNIT);
}

#[test]
fn v14_crowdfund_colectivo_pago_y_reembolso_individual() {
    let ctx = setup(Modo::Libre);
    let c1 = String::from_str(&ctx.env, "cf-release");
    let c2 = String::from_str(&ctx.env, "cf-refund");

    // Camino 1: cliente + tercero juntan pozo y el árbitro paga el total al programador.
    assert_eq!(ctx.c.create_crowdfund_task(&ctx.client, &c1, &(4 * UNIT), &DIA, &h(&ctx.env, 20)), 4 * UNIT);
    assert_eq!(ctx.c.pledge_crowdfund_task(&ctx.third, &c1, &4), 4 * UNIT + 4);
    assert_eq!(ctx.c.pledge_crowdfund_task(&ctx.client, &c1, &(1 * UNIT)), 5 * UNIT + 4);
    assert_eq!(
        ctx.c.release_crowdfund_task(&c1, &ctx.freelancer, &h(&ctx.env, 21), &h(&ctx.env, 22)),
        5 * UNIT + 4
    );
    assert_eq!(ctx.token.balance(&ctx.freelancer), 5 * UNIT + 4);

    // Camino 2: vence el plazo -> cada aportante recupera exactamente lo suyo.
    ctx.c.create_crowdfund_task(&ctx.client, &c2, &(2 * UNIT), &100, &h(&ctx.env, 23));
    ctx.c.pledge_crowdfund_task(&ctx.third, &c2, &3);
    assert_eq!(ctx.c.try_refund_crowdfund_task(&c2), Err(Ok(Error::DeadlineNotReached)));
    ctx.env.ledger().set_timestamp(START_TS + 100);
    assert_eq!(ctx.c.refund_crowdfund_task(&c2), 2);
    assert_eq!(ctx.c.try_refund_crowdfund_task(&c2), Err(Ok(Error::NotFunded)));
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.third), 3);
    cuadra(&ctx);
}

#[test]
fn v14_team_task_reparto_en_bps_y_reembolso() {
    let ctx = setup(Modo::Libre);
    let m2 = Address::generate(&ctx.env);
    let t1 = String::from_str(&ctx.env, "team-ok");
    let t2 = String::from_str(&ctx.env, "team-ref");

    let members = Vec::from_array(&ctx.env, [ctx.freelancer.clone(), m2.clone()]);
    let shares = Vec::from_array(&ctx.env, [7000u32, 3000u32]);
    ctx.c.deposit_team_task(&ctx.client, &t1, &members, &shares, &(10 * UNIT), &DIA, &h(&ctx.env, 30));

    assert_eq!(
        ctx.c.try_deposit_team_task(
            &ctx.client,
            &t2,
            &members,
            &Vec::from_array(&ctx.env, [5000u32, 4000u32]),
            &(2 * UNIT),
            &DIA,
            &h(&ctx.env, 31)
        ),
        Err(Ok(Error::InvalidAmount))
    );

    ctx.c.release_team_task(&t1, &h(&ctx.env, 32), &h(&ctx.env, 33));
    assert_eq!(ctx.token.balance(&ctx.freelancer), 7 * UNIT);
    assert_eq!(ctx.token.balance(&m2), 3 * UNIT);

    ctx.c.deposit_team_task(&ctx.client, &t2, &members, &shares, &(2 * UNIT), &100, &h(&ctx.env, 34));
    ctx.env.ledger().set_timestamp(START_TS + 100);
    assert_eq!(ctx.c.refund_team_task(&t2), 2 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 10 * UNIT);
    cuadra(&ctx);
}

#[test]
fn v14_cliff_stream_bloquea_hasta_cliff_y_desbloquea_retroactivo() {
    let ctx = setup(Modo::Libre);
    let s1 = String::from_str(&ctx.env, "cliff-1");
    let s2 = String::from_str(&ctx.env, "cliff-cancel");

    ctx.c.deposit_cliff_stream(&ctx.client, &s1, &ctx.freelancer, &(10 * UNIT), &(3 * DIA), &(10 * DIA));
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    assert_eq!(ctx.c.try_withdraw_stream(&s1), Err(Ok(Error::NothingToWithdraw)));

    ctx.env.ledger().set_timestamp(START_TS + 3 * DIA);
    assert_eq!(ctx.c.withdraw_stream(&s1), 3 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 3 * UNIT);

    ctx.c.deposit_cliff_stream(&ctx.client, &s2, &ctx.freelancer, &(5 * UNIT), &(4 * DIA), &(10 * DIA));
    ctx.c.cancel_stream(&s2);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 3 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 10 * UNIT);
    cuadra(&ctx);
}

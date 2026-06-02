from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..models.nation import Nation
from ..models.player import Player
from ..models.probe_data import ProbeData, ProbeDataAccess
from ..models.probe_market import ProbeMarketListing
from ..models.territory import Territory
from ..routers.auth import get_current_player
from ..schemas.nation import ProbeMarketListRequest, ProbeMarketListingResponse
from ..services.pathfinding import compute_reachable_ids

router = APIRouter(prefix="/api/probe-market", tags=["probe-market"])

_VALID_SORTS = {"mineral_richness", "fuel_richness", "total_richness", "price", "listed_at"}


def _build_reachable_set(nation_id: int, db: Session) -> set[int] | None:
    """Return territory IDs reachable from the buyer's empire, or None if no territories."""
    owned = db.query(Territory).filter(
        Territory.nation_id == nation_id,
        Territory.is_colonized == True,
    ).all()
    if not owned:
        return None
    all_territories = [
        {"id": t.id, "node_key": t.node_key, "territory_type": t.territory_type, "nation_id": t.nation_id}
        for t in db.query(Territory).all()
    ]
    reachable: set[int] = set()
    for t in owned:
        reachable |= compute_reachable_ids(t.node_key, nation_id, all_territories)
    return reachable


@router.get("", response_model=list[ProbeMarketListingResponse])
def browse_market(
    sort: str = Query(default="total_richness"),
    order: str = Query(default="desc"),
    reachable_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    if sort not in _VALID_SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of {_VALID_SORTS}")

    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    listings = db.query(ProbeMarketListing).all()
    if not listings:
        return []

    # Probe data IDs the caller already has access to (discovered or purchased)
    owned_probe_data_ids: set[int] = {
        pd.id for pd in db.query(ProbeData)
        .filter(ProbeData.discovered_by == nation.id).all()
    }
    purchased_probe_data_ids: set[int] = {
        row.probe_data_id for row in db.query(ProbeDataAccess)
        .filter(ProbeDataAccess.granted_to == nation.id).all()
    }
    have_ids = owned_probe_data_ids | purchased_probe_data_ids

    # Reachability: compute once up front
    reachable: set[int] | None = _build_reachable_set(nation.id, db) if reachable_only or True else None

    # Territory and nation lookup
    territory_ids = [lst.probe_data.territory_id for lst in listings]
    territories = {t.id: t for t in db.query(Territory).filter(Territory.id.in_(territory_ids)).all()}
    nation_ids = {t.nation_id for t in territories.values() if t.nation_id}
    nations_by_id = {n.id: n for n in db.query(Nation).filter(Nation.id.in_(nation_ids)).all()}
    seller_ids = {lst.seller_nation_id for lst in listings}
    sellers = {n.id: n for n in db.query(Nation).filter(Nation.id.in_(seller_ids)).all()}

    results = []
    for lst in listings:
        pd = lst.probe_data
        t = territories.get(pd.territory_id)
        if not t:
            continue

        seller_nation = sellers.get(lst.seller_nation_id)
        colonized_by_nation = nations_by_id.get(t.nation_id) if t.nation_id else None

        is_own = lst.seller_nation_id == nation.id
        already_have = pd.id in have_ids
        is_reachable = (t.id in reachable) if reachable is not None else None

        results.append(ProbeMarketListingResponse(
            id=lst.id,
            probe_data_id=pd.id,
            seller_nation_id=lst.seller_nation_id,
            seller_nation_name=seller_nation.name if seller_nation else f"Nation #{lst.seller_nation_id}",
            mineral_richness=float(pd.mineral_richness),
            fuel_richness=float(pd.fuel_richness),
            price=float(lst.price),
            listed_at=lst.listed_at.isoformat(),
            is_colonized=t.is_colonized,
            colonized_by_name=colonized_by_nation.name if colonized_by_nation else None,
            is_own=is_own,
            already_have=already_have,
            node_key=t.node_key if (is_own or already_have) else None,
            is_reachable=is_reachable,
        ))

    if reachable_only:
        results = [r for r in results if r.is_reachable]

    # Sort
    reverse = order != "asc"
    if sort == "mineral_richness":
        results.sort(key=lambda r: r.mineral_richness, reverse=reverse)
    elif sort == "fuel_richness":
        results.sort(key=lambda r: r.fuel_richness, reverse=reverse)
    elif sort == "total_richness":
        results.sort(key=lambda r: r.mineral_richness + r.fuel_richness, reverse=reverse)
    elif sort == "price":
        results.sort(key=lambda r: r.price, reverse=reverse)
    else:  # listed_at
        results.sort(key=lambda r: r.listed_at, reverse=reverse)

    return results


@router.post("", response_model=ProbeMarketListingResponse, status_code=201)
def create_listing(
    body: ProbeMarketListRequest,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    pd = db.get(ProbeData, body.probe_data_id)
    if not pd or pd.discovered_by != nation.id:
        raise HTTPException(status_code=403, detail="Probe data not found or does not belong to you")

    if body.price <= 0:
        raise HTTPException(status_code=422, detail="Price must be greater than 0")

    existing = db.query(ProbeMarketListing).filter(
        ProbeMarketListing.probe_data_id == body.probe_data_id,
        ProbeMarketListing.seller_nation_id == nation.id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="This probe data is already listed")

    listing = ProbeMarketListing(
        probe_data_id=pd.id,
        seller_nation_id=nation.id,
        price=body.price,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    t = db.get(Territory, pd.territory_id)
    colonized_by = db.get(Nation, t.nation_id) if t and t.nation_id else None

    return ProbeMarketListingResponse(
        id=listing.id,
        probe_data_id=pd.id,
        seller_nation_id=nation.id,
        seller_nation_name=nation.name,
        mineral_richness=float(pd.mineral_richness),
        fuel_richness=float(pd.fuel_richness),
        price=float(listing.price),
        listed_at=listing.listed_at.isoformat(),
        is_colonized=t.is_colonized if t else False,
        colonized_by_name=colonized_by.name if colonized_by else None,
        is_own=True,
        already_have=True,
        node_key=t.node_key if t else None,
        is_reachable=None,
    )


@router.delete("/{listing_id}", status_code=204)
def delete_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    listing = db.get(ProbeMarketListing, listing_id)
    if not listing or listing.seller_nation_id != nation.id:
        raise HTTPException(status_code=404, detail="Listing not found")

    db.delete(listing)
    db.commit()


@router.post("/{listing_id}/buy", response_model=ProbeMarketListingResponse)
def buy_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    player: Player = Depends(get_current_player),
):
    nation = db.query(Nation).filter(Nation.player_id == player.id).first()
    if not nation:
        raise HTTPException(status_code=404, detail="No nation found")

    listing = db.get(ProbeMarketListing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.seller_nation_id == nation.id:
        raise HTTPException(status_code=409, detail="Cannot buy your own listing")

    pd = listing.probe_data
    if not pd:
        raise HTTPException(status_code=410, detail="Probe data no longer exists")

    already = db.query(ProbeDataAccess).filter(
        ProbeDataAccess.probe_data_id == pd.id,
        ProbeDataAccess.granted_to == nation.id,
    ).first()
    if already:
        raise HTTPException(status_code=409, detail="You already own this probe data")

    own_discovery = db.query(ProbeData).filter(
        ProbeData.territory_id == pd.territory_id,
        ProbeData.discovered_by == nation.id,
    ).first()
    if own_discovery:
        raise HTTPException(status_code=409, detail="You already have probe data for this territory")

    if float(nation.currency) < float(listing.price):
        raise HTTPException(status_code=409, detail="Insufficient currency")

    nation.currency -= listing.price
    seller = db.get(Nation, listing.seller_nation_id)
    if seller:
        seller.currency += listing.price

    db.add(ProbeDataAccess(
        probe_data_id=pd.id,
        granted_to=nation.id,
        price_paid=listing.price,
    ))
    db.commit()

    t = db.get(Territory, pd.territory_id)
    colonized_by = db.get(Nation, t.nation_id) if t and t.nation_id else None

    return ProbeMarketListingResponse(
        id=listing.id,
        probe_data_id=pd.id,
        seller_nation_id=listing.seller_nation_id,
        seller_nation_name=seller.name if seller else f"Nation #{listing.seller_nation_id}",
        mineral_richness=float(pd.mineral_richness),
        fuel_richness=float(pd.fuel_richness),
        price=float(listing.price),
        listed_at=listing.listed_at.isoformat(),
        is_colonized=t.is_colonized if t else False,
        colonized_by_name=colonized_by.name if colonized_by else None,
        is_own=False,
        already_have=True,
        node_key=t.node_key if t else None,
        is_reachable=None,
    )

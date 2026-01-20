from fastapi import APIRouter, Query, HTTPException
from utils.geocoding import geocode_address, autocomplete_address

router = APIRouter(prefix="/geocoding", tags=["Geocoding"])

@router.get("/geocode")
async def get_coordinates(address: str = Query(..., description="Full address")):
    coords = await geocode_address(address)
    if coords:
        return {"lat": coords[0], "lon": coords[1]}
    raise HTTPException(status_code=404, detail="Address not found")

@router.get("/autocomplete")
async def get_suggestions(query: str = Query(..., description="Address part")):
    suggestions = await autocomplete_address(query)
    return {"suggestions": suggestions}

from sqlalchemy.orm import Session
from db.mysql import Feedback
from db.neo4j import run_query

def create_feedback(db: Session, event_id: str, event_title: str, field_name: str, proposed_value: str) -> bool:
    try:
        feedback = Feedback(
            event_id=event_id,
            event_title=event_title,
            field_name=field_name,
            proposed_value=proposed_value
        )
        db.add(feedback)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Error creating feedback: {e}")
        return False

def get_pending_feedbacks(db: Session) -> list[Feedback]:
    return db.query(Feedback).filter(Feedback.status == 'pending').order_by(Feedback.created_at.desc()).all()

def delete_feedbacks(db: Session, ids: list[int]) -> bool:
    try:
        db.query(Feedback).filter(Feedback.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Error deleting feedbacks: {e}")
        return False

def apply_feedbacks(db: Session, items: list) -> dict:
    success_count = 0
    errors = []
    
    for item in items:
        event_id = item.event_id
        field_name = item.field_name
        proposed_value = item.proposed_value.strip()
        
        try:
            # 1. Apply to Neo4j
            if field_name == 'locations':
                locs = [l.strip() for l in proposed_value.split(',') if l.strip()]
                # Delete old relationships
                del_cypher = "MATCH (e:Event {id: $event_id})-[r:HAPPENED_AT]->() DELETE r"
                run_query(del_cypher, {"event_id": event_id})
                
                # Create new relationships
                for loc in locs:
                    merge_cypher = """
                    MATCH (e:Event {id: $event_id})
                    MERGE (l:Location {name: $loc})
                    MERGE (e)-[:HAPPENED_AT]->(l)
                    """
                    run_query(merge_cypher, {"event_id": event_id, "loc": loc})
                    
            elif field_name in ('std_start_year', 'year'):
                try:
                    val = int(proposed_value)
                except ValueError:
                    val = proposed_value
                
                set_cypher = "MATCH (e:Event {id: $event_id}) SET e.std_start_year = $val"
                run_query(set_cypher, {"event_id": event_id, "val": val})
            else:
                target_field = "description" if field_name == "desc" else field_name
                set_cypher = f"MATCH (e:Event {{id: $event_id}}) SET e.{target_field} = $val"
                run_query(set_cypher, {"event_id": event_id, "val": proposed_value})
            
            # 2. Update status in MySQL to 'approved' using SQLAlchemy ORM
            feedback = db.query(Feedback).filter(Feedback.id == item.id).first()
            if feedback:
                feedback.status = 'approved'
                feedback.proposed_value = proposed_value
                db.commit()
                success_count += 1
            else:
                errors.append(f"Feedback ID {item.id} not found in database")
            
        except Exception as item_err:
            db.rollback()
            errors.append(f"Feedback ID {item.id} failed: {str(item_err)}")
            
    return {
        "success": len(errors) == 0,
        "applied_count": success_count,
        "errors": errors,
        "message": f"Successfully applied {success_count} feedbacks. Errors: {len(errors)}"
    }
